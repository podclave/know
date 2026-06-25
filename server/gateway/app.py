"""know gateway — the brain's single public front door (FastAPI).

Mounts the MCP-over-HTTP transport at the secret path /mcp/<secret>/<name>/ and
fulfills its four tools (recall/save/list/supersede) against the git-markdown
store + the recall `claude` agent.

Lifecycle (spec §10): spin-down-native. A `save` schedules an event-driven
secretary pass at the tail of the write that woke the box (debounced, single-flight,
holding a Sprite keep-alive so the box can't suspend mid-curation). The one event
the box can't see — an off-box mirror push — is handled by the wake.py CLI, which
a scheduler runs hourly to pull the mirror, reconcile if it moved, and report liveness.
"""
import asyncio
import hmac
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
from mcp_endpoint import build_router
from recall import recall as recall_agent
from secretary import contradiction_records, resolve_contradiction, run_pass
from kb_stats import kb_snapshot
from store import GitStore, _git
from viewer.generator import generate_html


# --- handlers: adapt store + recall to the MCP transport, formatting for the model -
class Handlers:
    """The injected dispatch target for mcp_endpoint. Store calls run off the event
    loop (git blocks); results are formatted to clean text the model reads well. A
    save schedules a curation pass (the event-driven secretary trigger)."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.store = GitStore(repo)

    async def recall(self, query: str, attribution: str) -> str:
        return await recall_agent(query, repo=self.repo)

    async def save(self, title, body, type, tags, source, attribution) -> str:
        r = await asyncio.to_thread(self.store.save, title, body, type, tags, source, attribution)
        note_write()  # tail-of-write curation trigger (§10 lifecycle)
        return f"Saved \"{r['title']}\" to the team brain (id {r['id']})."

    async def list(self, filt) -> str:
        r = await asyncio.to_thread(self.store.list, filt)
        if not r["facts"]:
            scope = f" matching \"{filt}\"" if filt else ""
            return f"No facts{scope} in the knowledge base yet."
        lines = [f"{f['id']}  [{f['status']}/{f['type']}]  {f['title']}" for f in r["facts"]]
        head = f"{r['count']} fact(s)" + (f" matching \"{filt}\"" if filt else "") + ":"
        return head + "\n" + "\n".join(lines)

    async def supersede(self, fact_id, by, attribution) -> str:
        r = await asyncio.to_thread(self.store.supersede, fact_id, by, attribution)
        tail = f", replaced by {by}" if by else ""
        return f"Superseded \"{r['title']}\" (id {fact_id}){tail}. Moved to _superseded/ (not deleted)."

    async def contradictions(self) -> str:
        recs = await asyncio.to_thread(contradiction_records, self.repo)
        if not recs:
            return "No open contradictions — the knowledge base has no unresolved disputes."
        out = [f"{len(recs)} open contradiction(s) awaiting a decision:"]
        for r in recs:
            who = ", ".join(map(str, r["sources"])) if r["sources"] else "unknown"
            out.append(
                f"\n• id: {r['id']}  (disputed concept: {r['target']}; raised by: {who})\n"
                f"{r['body']}\n"
                f"  → resolve with: resolve(id=\"{r['id']}\", decision=\"keep\" or "
                f"\"replace\", correction=…)")
        return "\n".join(out)

    async def resolve(self, ident, decision, correction, note, attribution) -> str:
        try:
            r = await asyncio.to_thread(resolve_contradiction, self.repo, ident, decision,
                                        text=correction, note=note, actor=attribution)
        except ValueError as e:
            return f"Could not resolve: {e}"
        if r["status"] == "busy":
            return "The brain is curating right now — re-run resolve in a few seconds."
        verb = ("updated the curated fact" if r["curated_updated"]
                else "kept the existing curated fact")
        return (f"Resolved the dispute on \"{r['target']}\": {verb} (decided by "
                f"{r['actor']}). The contradiction is closed and archived to "
                f"contradictions/resolved/ as an audit trail.")


KB_REPO = config.KB_REPO
app = FastAPI(title="know", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(build_router(config.SECRET, Handlers(KB_REPO)))


# --- event-driven secretary trigger (spec §10) -------------------------------
# Debounced single-flight: a save sets writes>0; a background task fires a curation
# pass after a short quiet window, at most once per MIN_SECS, holding a Sprite
# keep-alive so the box can't suspend mid-pass. Lifted from podbrain app.py note_writes.
CURATE = {"writes": 0, "last_run": 0.0, "scheduled": False}
CURATE_MIN_SECS = 300       # min seconds between event-driven (on-box) curation passes
CURATE_DEBOUNCE = 20        # quiet window after a save before a curation pass fires
CURATE_DRAIN_SECS = 5       # gap before re-firing when raw/ still has backlog to drain
SPRITE_SOCK = "/.sprite/api.sock"   # Sprite tasks API (keep-alive); no-op off-Sprite
KEEPALIVE = "know-curating"


async def _sprite_api(method: str, path: str, payload: dict | None = None):
    """Local Sprite tasks API over its unix socket — a keep-alive task so the box
    can't auto-suspend mid-curation. No-op-on-error (best effort; off-Sprite too)."""
    transport = httpx.AsyncHTTPTransport(uds=SPRITE_SOCK)
    async with httpx.AsyncClient(transport=transport, base_url="http://sprite", timeout=10) as c:
        return await c.request(method, path, json=payload)


async def _curate(reason: str) -> dict:
    try:
        await _sprite_api("POST", "/v1/tasks", {"name": KEEPALIVE, "expire": "10m"})
    except Exception:  # noqa: BLE001
        pass
    try:
        result = await asyncio.to_thread(run_pass, KB_REPO)
    finally:
        CURATE.update(writes=0, last_run=time.time(), scheduled=False)
        try:
            await _sprite_api("DELETE", f"/v1/tasks/{KEEPALIVE}")
        except Exception:  # noqa: BLE001
            pass
    # Self-retrigger: a pass is budget/turn-bounded, so a backlog bigger than one pass
    # can drain (e.g. a bulk ingest) leaves raw/ non-empty. Re-fire soon so it drains in
    # minutes rather than one chunk per hourly wake run. Guarded on real progress
    # (moved_to_superseded>0) so a fact that can't be represented can't spin a tight loop.
    if (isinstance(result, dict) and result.get("status") == "committed"
            and result.get("raw_remaining", 0) > 0
            and result.get("moved_to_superseded", 0) > 0
            and not CURATE["scheduled"]):
        CURATE["scheduled"] = True
        try:
            asyncio.get_running_loop().create_task(_drain_curate())
        except RuntimeError:
            CURATE["scheduled"] = False  # no loop (e.g. a sync test) — skip
    return result


async def _drain_curate():
    await asyncio.sleep(CURATE_DRAIN_SECS)
    await _curate("drain-backlog")


async def _debounced_curate():
    await asyncio.sleep(CURATE_DEBOUNCE)
    if (time.time() - CURATE["last_run"]) < CURATE_MIN_SECS and CURATE["last_run"]:
        CURATE["scheduled"] = False  # too soon; the next wake run or save will cover it
        return
    await _curate("activity")


def note_write(n: int = 1):
    CURATE["writes"] += n
    if not CURATE["scheduled"]:
        CURATE["scheduled"] = True
        try:
            asyncio.get_running_loop().create_task(_debounced_curate())
        except RuntimeError:
            CURATE["scheduled"] = False  # no loop (e.g. a sync test) — skip


# --- endpoints ----------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    """Liveness + cheap KB inventory for operators (no agent calls)."""
    stats = await asyncio.to_thread(kb_snapshot, KB_REPO)
    return {
        "status": "ok",
        "service": "know",
        "name": config.NAME,
        **stats,
        "curation_scheduled": CURATE["scheduled"],
        "curation_writes_pending": CURATE["writes"],
    }


# --- viewer: the OKF static graph visualizer over the curated bundle ---------
# Secret-gated by the SAME capability-URL pattern as /mcp (the secret is in the path,
# wrong/missing -> plain 404). Renders the curated/ OKF bundle as a self-contained
# interactive graph; generated on demand so it's always current.
def _viewer_html() -> str:
    return generate_html(KB_REPO / "curated", bundle_name=config.NAME)


async def _viewer(path_secret: str):
    if not (config.SECRET and hmac.compare_digest(path_secret.encode(), config.SECRET.encode())):
        return JSONResponse({"detail": "not found"}, status_code=404)
    html = await asyncio.to_thread(_viewer_html)
    return HTMLResponse(html)


app.add_api_route("/viewer/{path_secret}/", _viewer, methods=["GET"])
app.add_api_route("/viewer/{path_secret}", _viewer, methods=["GET"])


