"""MCP-over-HTTP endpoint (stateless Streamable HTTP) for the know brain.

Lifted from podbrain's gateway/mcp_endpoint.py — the JSON-RPC / Streamable-HTTP
layer (initialize / ping / tools/list / tools/call, notification->202, error
codes, isError wrapping, _tool_result). Two deliberate changes for v4:

  1. AUTH IS A SECRET PATH SEGMENT, not a bearer header. The server is a no-auth
     MCP server reachable at /mcp/<secret>/<name>/ (spec §9): every connector
     surface (Claude Code, claude.ai, Desktop, Cowork) just adds the URL — the
     URL IS the credential. We hmac.compare_digest the <secret> segment and
     capture <name> for attribution. A wrong/missing secret returns a plain 404
     — NOT a 401 with WWW-Authenticate, which would trip an OAuth flow the brain
     doesn't run.

  2. The tool surface is recall / save / list / supersede, dispatched to an
     injected `handlers` object (the git-markdown store + the recall agent), so
     this transport layer is testable with a fake handler — no git, no claude.

Stateless by design: every tool is one request/response. No sessions, no SSE,
so GET/DELETE on the path return 405 (the no-stream behavior the spec permits).
"""
import hmac
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
LATEST_PROTOCOL = "2025-06-18"
SERVER_INFO = {"name": "know", "version": "1.0.0"}


def _t(name, description, properties, required=None):
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


_STR = lambda d: {"type": "string", "description": d}                       # noqa: E731
_ARR = lambda d: {"type": "array", "items": {"type": "string"}, "description": d}  # noqa: E731

# Tool descriptions ARE product surface — they steer the model's save/recall
# behavior on every surface (spec §6.3: tune `save` to self-trigger aggressively,
# including on cowork-shaped signals, not just CLI code-learnings).
TOOLS = [
    _t("recall",
       "Search the team's shared knowledge base — durable facts, decisions, "
       "conventions, infra details, and gotchas the team has saved. Call this "
       "whenever the user asks about their team, project, codebase, infra, or "
       "past decisions, BEFORE answering from assumptions: the brain may hold a "
       "fact you don't have. Returns relevant content with an honest confidence "
       "signal — it tells you when it found nothing or only partial matches, so "
       "treat a low-confidence result as 'the brain may not know this', never as "
       "an authoritative 'the team has no such thing'.",
       {"query": _STR("What to look up — keywords, a question, file names, or concepts")},
       required=["query"]),
    _t("save",
       "Persist a durable team/project fact the USER has approved saving, so "
       "teammates and future sessions can recall it. Do NOT call this on your own "
       "initiative: first PROPOSE the fact(s) to the user — a short title plus the "
       "fact — and wait for an explicit go-ahead, then save only what they approved. "
       "One fact per call. Good facts are durable and specific: an infra/architecture "
       "detail (services, endpoints, owners, versions, ports), a decision, a "
       "convention, or a gotcha/known-issue. Never save secrets/tokens/keys, generic "
       "advice, or transient chatter.",
       {"title": _STR("Short descriptive title for the fact"),
        "body": _STR("The fact itself — specific and self-contained"),
        "type": _STR("Kind of fact: Fact, Decision, Convention, Gotcha, Runbook, "
                     "Architecture, or Reference (default Fact)"),
        "tags": _ARR("Optional keywords/categories this fact should be findable by"),
        "source": _STR("Optional provenance note (e.g. 'from the architecture doc', 'decided in standup')")},
       required=["title", "body"]),
    _t("list",
       "List facts currently in the knowledge base (ids + titles). Pass an "
       "optional filter substring to narrow it. Use to see what the brain "
       "already knows, or to find the id of a fact you want to supersede.",
       {"filter": _STR("Optional case-insensitive substring to match titles/tags")}),
    _t("supersede",
       "Retire a fact that is now wrong or outdated — optionally noting the fact "
       "that replaces it. Never deletes: the old fact is moved aside so history "
       "is preserved and the change is reversible. Find the id with `list`.",
       {"id": _STR("The id of the fact to retire (from `list` or `recall`)"),
        "by": _STR("Optional id or title of the fact that replaces it")},
       required=["id"]),
    _t("contradictions",
       "List the OPEN contradictions in the team brain — facts where a newer claim "
       "conflicts with what's already curated, awaiting a human's decision. Call this "
       "when the user asks what's disputed/contested/unresolved, or to find the id of "
       "a dispute to `resolve`. Returns each dispute's id, the disputed concept, the "
       "curated fact vs the conflicting claim, and who raised it.",
       {}),
    _t("resolve",
       "Resolve an open contradiction (from `contradictions`, or a recall result "
       "flagged DISPUTED) by recording the human's decision — no git or file editing "
       "needed. The USER must make the call; you only carry it out. Use "
       "decision='keep' if the existing curated fact is right (the conflicting claim "
       "was wrong), or decision='replace' if the fact should change — then put the "
       "corrected fact in `correction`. The decision is attributed to the caller and "
       "archived as an audit trail.",
       {"id": _STR("The contradiction id from `contradictions` (e.g. 'database.md')"),
        "decision": _STR("'keep' (curated fact stands) or 'replace' (update the fact)"),
        "correction": _STR("Required for 'replace': the corrected fact text to store"),
        "note": _STR("Optional short note on why/how it was decided")},
       required=["id", "decision"]),
]


class ToolError(Exception):
    """Argument-validation failure — surfaced as an MCP tool error, not a 500."""


def _req_str(args: dict, key: str) -> str:
    v = args.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ToolError(f"{key} is required")
    return v.strip()


def _opt_str(args: dict, key: str):
    v = args.get(key)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _norm_list(v):
    """Comma-string or array -> trimmed list."""
    if isinstance(v, list):
        return [s.strip() for s in v if isinstance(s, str) and s.strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []


async def call_tool(name: str, args: dict, attribution: str, handlers):
    """Validate args, dispatch to the injected handler. Raises ToolError on bad
    args (-> MCP isError), lets handler exceptions bubble (-> visible tool error)."""
    if name == "recall":
        return await handlers.recall(_req_str(args, "query"), attribution)
    if name == "save":
        return await handlers.save(
            title=_req_str(args, "title"), body=_req_str(args, "body"),
            type=_opt_str(args, "type"), tags=_norm_list(args.get("tags")),
            source=_opt_str(args, "source"), attribution=attribution)
    if name == "list":
        return await handlers.list(_opt_str(args, "filter"))
    if name == "supersede":
        return await handlers.supersede(_req_str(args, "id"), _opt_str(args, "by"), attribution)
    if name == "contradictions":
        return await handlers.contradictions()
    if name == "resolve":
        decision = _req_str(args, "decision").lower()
        if decision not in ("keep", "replace"):
            raise ToolError("decision must be 'keep' or 'replace'")
        correction = _opt_str(args, "correction")
        if decision == "replace" and not correction:
            raise ToolError("decision 'replace' requires the corrected fact in `correction`")
        return await handlers.resolve(
            ident=_req_str(args, "id"), decision=decision,
            correction=correction, note=_opt_str(args, "note"), attribution=attribution)
    raise ToolError(f"unhandled tool: {name}")  # a TOOLS entry with no dispatch branch


def _tool_result(payload) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        return payload  # already MCP-shaped
    if isinstance(payload, str):
        return {"content": [{"type": "text", "text": payload}]}
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def build_router(secret: str, handlers) -> APIRouter:
    """Mount the MCP transport at /mcp/<secret>/<name>/. `handlers` is any object
    exposing async recall/save/list/supersede (the real store, or a fake in tests)."""
    router = APIRouter()

    def _rpc(id_, **kv):
        return JSONResponse({"jsonrpc": "2.0", "id": id_, **kv})

    def _err(id_, code, msg):
        return _rpc(id_, error={"code": code, "message": msg})

    async def mcp_post(path_secret: str, name: str, request: Request):
        # Wrong/missing secret -> plain 404. No WWW-Authenticate (would trip OAuth).
        if not (secret and _eq(path_secret, secret)):
            return JSONResponse({"detail": "not found"}, status_code=404)
        attribution = (name or "unknown").strip() or "unknown"
        try:
            msg = json.loads(await request.body() or b"null")
        except ValueError:
            return _err(None, -32700, "parse error")
        if not isinstance(msg, dict):
            return _err(None, -32600, "request must be a single JSON-RPC object (batching not supported)")
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}
        if msg_id is None:  # notification (e.g. notifications/initialized)
            return Response(status_code=202)
        if not isinstance(params, dict):
            return _err(msg_id, -32602, "params must be an object")
        if method == "initialize":
            ver = params.get("protocolVersion")
            return _rpc(msg_id, result={
                "protocolVersion": ver if ver in PROTOCOL_VERSIONS else LATEST_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO})
        if method == "ping":
            return _rpc(msg_id, result={})
        if method == "tools/list":
            return _rpc(msg_id, result={"tools": TOOLS})
        if method == "tools/call":
            tname = params.get("name")
            if not any(t["name"] == tname for t in TOOLS):
                return _err(msg_id, -32602, f"unknown tool: {tname}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _err(msg_id, -32602, "arguments must be an object")
            try:
                payload = await call_tool(tname, arguments, attribution, handlers)
            except ToolError as e:
                return _rpc(msg_id, result={
                    "isError": True, "content": [{"type": "text", "text": str(e)}]})
            except Exception as e:  # noqa: BLE001 — store/agent failure must be
                # visible to the model (a down brain is a tool error, never silent)
                return _rpc(msg_id, result={
                    "isError": True,
                    "content": [{"type": "text", "text": f"know call failed: {e}"}]})
            return _rpc(msg_id, result=_tool_result(payload))
        return _err(msg_id, -32601, f"method not found: {method}")

    # Register both trailing-slash variants explicitly (no 307 redirect, which some
    # MCP clients mishandle). Only POST -> GET/DELETE get Starlette's 405 (no-stream).
    router.add_api_route("/mcp/{path_secret}/{name}/", mcp_post, methods=["POST"])
    router.add_api_route("/mcp/{path_secret}/{name}", mcp_post, methods=["POST"])
    return router
