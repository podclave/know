"""know gateway — the brain's single public front door (FastAPI).

Mounts the MCP-over-HTTP transport at the secret path /mcp/<secret>/<name>/ and
fulfills its four tools (recall/save/list/supersede) against the git-markdown
store + the recall `claude` agent.

Lifecycle (spec §10): spin-down-native. A `save` schedules an event-driven
secretary pass at the tail of the write that woke the box (debounced, single-flight,
holding a Sprite keep-alive so the box can't suspend mid-curation). The one event
the box can't see — an off-box mirror push — rides the external /wake pinger, which
also runs the auth probe + a curator-liveness check and alerts on auth failure.
"""
import asyncio
import hmac
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
from boot_check import auth_probe
from mcp_endpoint import build_router
from recall import recall as recall_agent
from secretary import contradiction_records, resolve_contradiction, run_pass
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
CURATE_MIN_SECS = int(os.environ.get("BRAIN_CURATE_MIN_SECS", "300"))
CURATE_DEBOUNCE = int(os.environ.get("BRAIN_CURATE_DEBOUNCE_SECS", "20"))
SPRITE_SOCK = os.environ.get("SPRITE_SOCK", "/.sprite/api.sock")
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
        return await asyncio.to_thread(run_pass, KB_REPO)
    finally:
        CURATE.update(writes=0, last_run=time.time(), scheduled=False)
        try:
            await _sprite_api("DELETE", f"/v1/tasks/{KEEPALIVE}")
        except Exception:  # noqa: BLE001
            pass


async def _debounced_curate():
    await asyncio.sleep(CURATE_DEBOUNCE)
    if (time.time() - CURATE["last_run"]) < CURATE_MIN_SECS and CURATE["last_run"]:
        CURATE["scheduled"] = False  # too soon; the next /wake or save will cover it
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
    return {"status": "ok", "service": "know", "brain": config.BRAIN_NAME}


# --- viewer: the OKF static graph visualizer over the curated bundle ---------
# Secret-gated by the SAME capability-URL pattern as /mcp (the secret is in the path,
# wrong/missing -> plain 404). Renders the curated/ OKF bundle as a self-contained
# interactive graph; generated on demand so it's always current.
def _viewer_html() -> str:
    return generate_html(KB_REPO / "curated", bundle_name=config.BRAIN_NAME)


async def _viewer(path_secret: str):
    if not (config.SECRET and hmac.compare_digest(path_secret.encode(), config.SECRET.encode())):
        return JSONResponse({"detail": "not found"}, status_code=404)
    html = await asyncio.to_thread(_viewer_html)
    return HTMLResponse(html)


app.add_api_route("/viewer/{path_secret}/", _viewer, methods=["GET"])
app.add_api_route("/viewer/{path_secret}", _viewer, methods=["GET"])


async def _alert(text: str):
    """Push an out-of-band alert (Slack webhook) on auth failure — a spun-down box
    can't cron itself, so /wake is the only place this fires. Best-effort."""
    hook = os.environ.get("BRAIN_ALERT_WEBHOOK", "").strip()
    if not hook:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(hook, json={"text": f"[know:{config.BRAIN_NAME}] {text}"})
    except Exception:  # noqa: BLE001
        pass


def _last_secretary_age() -> float | None:
    """Seconds since the last secretary commit (curator-liveness), or None."""
    out = _git(KB_REPO, "log", "--format=%ct", f"--author={config.SECRETARY_IDENTITY[1]}",
               "-1", check=False).stdout.strip()
    return (time.time() - float(out)) if out else None


@app.post("/wake")
@app.get("/wake")
async def wake():
    """The external-heartbeat route (spec §10.8): auth probe (+alert), pull the
    off-box mirror, reconcile (curation pass) if it brought human edits, and report
    curator liveness. Plain HTTP — the external pinger just poke this."""
    out = {"brain": config.BRAIN_NAME, "woke": time.time()}

    # 1. auth probe — distinct, loud, alerts out-of-band on failure
    ok, msg = await asyncio.to_thread(auth_probe)
    out["auth"] = "ok" if ok else "FAILED"
    if not ok:
        out["auth_detail"] = msg
        await _alert(f"AUTH FAILURE: {msg}")

    # 2. pull the mirror (the one event the box can't see) + reconcile if it moved
    try:
        remotes = _git(KB_REPO, "remote", check=False).stdout.split()
        if config.MIRROR_REMOTE in remotes:
            before = _git(KB_REPO, "rev-parse", "HEAD", check=False).stdout.strip()
            await asyncio.to_thread(_git, KB_REPO, "pull", "--ff-only",
                                    config.MIRROR_REMOTE, check=False)
            after = _git(KB_REPO, "rev-parse", "HEAD", check=False).stdout.strip()
            out["mirror"] = "pulled new commits" if before != after else "up to date"
            if before != after and ok:
                out["reconcile"] = (await _curate("wake-reconcile")).get("status")
    except Exception as e:  # noqa: BLE001
        out["mirror_error"] = str(e)

    # 3. curator liveness + the human-resolvable contradiction backlog
    age = await asyncio.to_thread(_last_secretary_age)
    out["last_curation_secs_ago"] = round(age) if age is not None else None
    from secretary import open_contradictions
    out["open_contradictions"] = len(open_contradictions(KB_REPO))
    return out
