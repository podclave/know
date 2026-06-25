#!/usr/bin/env python3
"""know commit-nudge — a tiny UserPromptSubmit hook (stdlib only).

It NEVER saves anything. When a session has accrued substance and nothing has been
committed to the team brain recently, it injects a short reminder (printed to stdout,
which a UserPromptSubmit hook adds to the turn's context) so the live model can PROPOSE
candidate facts the user then curates. State is read from the transcript — no state
files. Replaces the old background distiller: the live model is a better distiller and
already holds the conversation.

Tunables (env): KNOW_NUDGE=0 disables; KNOW_NUDGE_MIN_TURNS (default 6) is the substance
floor before the first nudge; KNOW_NUDGE_GAP_TURNS (default 8) is the spacing between
nudges.
"""
import json
import os
import sys

MARKER = "<know-nudge>"

NUDGE = (
    MARKER + " This session has covered some ground and nothing has been committed to "
    "the team brain recently. After you finish addressing the user's message above, IF "
    "the conversation has established durable, specific team/project facts worth keeping "
    "(a decision, a convention, an infra/architecture detail, or a gotcha), briefly list "
    "them as a numbered set of candidate facts and offer to save them — then call the "
    "`save` tool ONLY for the ones the user explicitly approves. Never save anything "
    "without an explicit yes. If nothing here is durable, say nothing about saving. "
    "</know-nudge>"
)


def _env_int(name, default):
    try:
        return int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def _is_user_prompt(obj):
    """A real user turn — not an injected/meta context line, not a tool result."""
    if obj.get("type") != "user" or obj.get("isMeta"):
        return False
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(c, dict) and c.get("type") == "text"
                   and (c.get("text") or "").strip() for c in content)
    return False


def _has_save(obj):
    if obj.get("type") != "assistant":
        return False
    for c in (obj.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_use" and "save" in (c.get("name") or ""):
            return True
    return False


def should_nudge(lines, min_turns, gap_turns):
    """Fire only if: enough substance has accrued, no save has happened since the last
    nudge (the user is not already curating), and enough turns have passed since the
    last nudge marker. The marker is matched as a raw substring so detection does not
    depend on how injected context is recorded."""
    last = -1
    for i, ln in enumerate(lines):
        if MARKER in ln:
            last = i
    after = lines[last + 1:] if last >= 0 else lines
    objs = []
    for ln in after:
        try:
            objs.append(json.loads(ln))
        except Exception:
            continue
    if any(_has_save(o) for o in objs):
        return False
    user_turns = sum(1 for o in objs if _is_user_prompt(o))
    threshold = min_turns if last < 0 else gap_turns
    return user_turns >= threshold


def main():
    if (os.environ.get("KNOW_NUDGE", "1") or "").strip().lower() in ("0", "false", "no"):
        return
    try:
        d = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    tr = d.get("transcript_path")
    if not tr or not os.path.isfile(tr):
        return
    try:
        with open(tr, errors="replace") as f:
            lines = f.read().splitlines()
    except Exception:
        return
    if not lines:
        return
    if should_nudge(lines, _env_int("KNOW_NUDGE_MIN_TURNS", 6),
                    _env_int("KNOW_NUDGE_GAP_TURNS", 8)):
        print(NUDGE)


if __name__ == "__main__":
    main()
