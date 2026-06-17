"""Recall — a cheap-tier `claude` agent over the KB repo (spec §5).

The lookup any Claude would do over a project, relocated server-side: run a read-only
agent (Read/Grep/Glob) over the repo via the Claude Agent SDK (see agent.py), curated/
first and raw/ on a miss, and return relevant content. The §5.5 anti-silent-rot
observables (curated-K vs raw-M counts, empty-brain honesty, auth-invalid loud message)
are computed deterministically here — never left to the cheap model.
"""
import re
from pathlib import Path

from agent import RECALL_BUDGET_USD, collect
from config import KB_REPO, model_id

RECALL_PROMPT = """Your ONLY job is to answer a recall query over this team knowledge base by \
searching the files in this repository. Do NOT take any other action.

The knowledge base layout:
- curated/ — the polished, deduped facts (an OKF bundle; curated/index.md maps it and \
concepts cross-link each other). SEARCH HERE FIRST.
- raw/ — append-only raw captures. Fall through to here only if curated/ doesn't answer it.
- _superseded/ — retired facts. IGNORE these; they are outdated.

Each fact file has YAML frontmatter (type/title/description/tags/timestamp) and a body. \
Use Grep and Read to find facts relevant to the query. Return the relevant fact \
content concisely, in your own words where helpful, and cite the fact titles.

Honesty rules (critical):
- If you find clearly relevant facts, return them.
- If you find nothing relevant, say so plainly: "No relevant facts found in the \
knowledge base." Do NOT invent or infer facts that aren't written down.
- If you find only loosely related material, return it but flag it as a partial / \
low-confidence match. Never present a guess as an established team fact.

QUERY: {query}"""


def _counts(repo: Path):
    def n(sub):
        d = repo / sub
        if not d.is_dir():
            return 0
        # exclude the reserved OKF index.md so an empty curated bundle reads as 0
        return len([f for f in d.glob("*.md") if f.name != "index.md"])
    return n("curated"), n("raw")


async def recall(query: str, repo: Path | None = None, model: str | None = None,
                 timeout: int = 120) -> str:
    repo = Path(repo or KB_REPO)
    curated, raw = _counts(repo)
    # Empty brain: an honest "nothing saved", explicitly NOT a failed lookup (§5.5).
    if curated == 0 and raw == 0:
        return ("(The team knowledge base is empty — nothing has been saved yet. "
                "This is an empty brain, not a failed lookup. If you just learned "
                "something durable, consider calling `save`.)")
    model = model or model_id(repo)
    res = await collect(RECALL_PROMPT.format(query=query), cwd=repo, model=model,
                        allowed_tools=["Read", "Grep", "Glob"], write=False,
                        max_turns=20, budget=RECALL_BUDGET_USD, timeout=timeout)
    if res.is_error:
        # Distinct, loud auth message (§5.5) vs a generic agent failure.
        if re.search(r"auth|credential|api[\s_-]?key|401|unauthor|invalid x-api|forbidden",
                     res.error, re.I):
            raise RuntimeError("brain auth invalid — the ANTHROPIC_API_KEY on the box "
                               "is missing/revoked/over-quota; recall is down until it's fixed")
        raise RuntimeError(f"recall agent failed: {res.error[:300]}")
    text = res.text or "(No relevant facts found in the knowledge base.)"
    # §5.5 count signal: a curated hit can still be incomplete if raw >> curated.
    if raw and (curated == 0 or raw > max(5, curated * 3)):
        text += (f"\n\n— recall signal: {curated} curated fact(s) vs ~{raw} raw "
                 f"candidate(s). If this looks thin, the secretary may be behind; "
                 f"more unorganized facts may exist in raw/.")
    return text
