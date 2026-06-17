"""teamkb gateway — the brain's single public front door (FastAPI).

Mounts the MCP-over-HTTP transport at the secret path /mcp/<secret>/<name>/ and
fulfills its four tools (recall/save/list/supersede) against the git-markdown
store + the recall `claude` agent. Plus /healthz (liveness) and /wake (the
external-heartbeat route: auth probe + pull-mirror + reconcile + liveness).
"""
import asyncio
import os
import time
from pathlib import Path

from fastapi import FastAPI

import config
from mcp_endpoint import build_router
from recall import recall as recall_agent
from store import GitStore


# --- handlers: adapt store + recall to the MCP transport, formatting for the model -
class Handlers:
    """The injected dispatch target for mcp_endpoint. Store calls run off the event
    loop (git blocks); results are formatted to clean text the model reads well."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.store = GitStore(repo)

    async def recall(self, query: str, attribution: str) -> str:
        return await recall_agent(query, repo=self.repo)

    async def save(self, title, body, aliases, source, attribution) -> str:
        r = await asyncio.to_thread(self.store.save, title, body, aliases, source, attribution)
        return f"Saved \"{r['title']}\" to the team brain (id {r['id']})."

    async def list(self, filt) -> str:
        r = await asyncio.to_thread(self.store.list, filt)
        if not r["facts"]:
            scope = f" matching \"{filt}\"" if filt else ""
            return f"No facts{scope} in the knowledge base yet."
        lines = [f"{f['id']}  [{f['status']}]  {f['title']}" for f in r["facts"]]
        head = f"{r['count']} fact(s)" + (f" matching \"{filt}\"" if filt else "") + ":"
        return head + "\n" + "\n".join(lines)

    async def supersede(self, fact_id, by, attribution) -> str:
        r = await asyncio.to_thread(self.store.supersede, fact_id, by, attribution)
        tail = f", replaced by {by}" if by else ""
        return f"Superseded \"{r['title']}\" (id {fact_id}){tail}. Moved to _superseded/ (not deleted)."


KB_REPO = config.KB_REPO
app = FastAPI(title="teamkb", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(build_router(config.SECRET, Handlers(KB_REPO)))


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "teamkb", "brain": config.BRAIN_NAME}


# --- /wake — the external-heartbeat route (spec §10.8). Fleshed out in Phase 5;
# for now it pulls the mirror and reports liveness so the route exists end-to-end.
@app.post("/wake")
@app.get("/wake")
async def wake():
    out = {"woke": time.time(), "brain": config.BRAIN_NAME}
    # pull the off-box mirror (the one event the box can't see) — best-effort
    try:
        from store import _git
        if config.MIRROR_REMOTE in _git(KB_REPO, "remote", check=False).stdout.split():
            await asyncio.to_thread(_git, KB_REPO, "pull", "--ff-only",
                                    config.MIRROR_REMOTE, check=False)
            out["mirror"] = "pulled"
    except Exception as e:  # noqa: BLE001
        out["mirror_error"] = str(e)
    return out
