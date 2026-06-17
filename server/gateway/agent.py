"""Server-side agent invocation via the Claude Agent SDK (`claude-agent-sdk`).

Replaces shelling out to `claude -p`. The SDK bundles a pinned, native (Node-free)
Claude Code CLI inside the venv, so the brain's agent runtime is self-contained,
version-reproducible across installs, and isolated from the box owner's interactive
`claude`. That removes the install-time Node / `claude update` / version-floor / PATH
dance and makes standing a brain up on any host (Sprite, droplet, …) a `pip install`.

Two callers:
  • recall (read-only, returns prose)  -> await collect(...)
  • secretary (read+write, returns a schema-validated manifest) -> run_sync(...)

Both surface cost + token usage from the SDK ResultMessage. Safety for the secretary
stays the deterministic post-hoc enforcement in secretary.py (never-rm / human-wins /
blast / concurrency) — this module just runs the agent and reports what came back.
"""
import os
from dataclasses import dataclass

import anyio
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage,
                              TextBlock, query)

from config import GUARD_ENV

# Generous wall-clock + cost ceilings — real passes run well under these; they only
# bound a runaway. max_budget_usd makes the agent stop itself when exceeded.
RECALL_BUDGET_USD = 0.50
SECRETARY_BUDGET_USD = 1.00


@dataclass
class AgentResult:
    text: str = ""
    structured: dict | None = None
    cost_usd: float | None = None
    tokens: dict | None = None
    is_error: bool = False
    error: str = ""


async def collect(prompt: str, *, cwd, model: str, allowed_tools: list[str],
                  write: bool = False, schema: dict | None = None,
                  max_turns: int = 30, budget: float | None = None,
                  timeout: int = 300) -> AgentResult:
    """Run one agent task to completion and normalize the result. Read-only by default;
    `write=True` flips permission_mode to acceptEdits. `schema` forces a structured
    manifest (returned in AgentResult.structured). Never raises — failures land in
    is_error/error so callers handle them uniformly."""
    opts = ClaudeAgentOptions(
        model=model, cwd=str(cwd),
        allowed_tools=allowed_tools, disallowed_tools=["Bash"],
        permission_mode="acceptEdits" if write else "default",
        setting_sources=None,                       # isolate from the box's ~/.claude
        env=dict(os.environ, **{GUARD_ENV: "1"}),    # full env (keeps auth) + recursion guard
        max_turns=max_turns, max_budget_usd=budget,
        output_format=({"type": "json_schema", "schema": schema} if schema else None))
    res = AgentResult()
    texts: list[str] = []
    try:
        with anyio.fail_after(timeout):
            async for msg in query(prompt=prompt, options=opts):
                if isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock) and b.text:
                            texts.append(b.text)
                elif isinstance(msg, ResultMessage):
                    res.cost_usd = msg.total_cost_usd
                    u = msg.usage or {}
                    res.tokens = {"in": u.get("input_tokens"), "out": u.get("output_tokens")}
                    res.structured = msg.structured_output if isinstance(msg.structured_output, dict) else None
                    if msg.is_error:
                        res.is_error = True
                        res.error = msg.subtype or "agent error"
    except TimeoutError:
        res.is_error, res.error = True, f"agent timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001 — surface any SDK/transport error uniformly
        res.is_error, res.error = True, f"{type(e).__name__}: {e}"
    res.text = "\n".join(texts).strip()
    return res


def run_sync(**kw) -> AgentResult:
    """Drive `collect` from a synchronous caller (the secretary runs in a worker
    thread with no event loop)."""
    return anyio.run(lambda: collect(**kw))
