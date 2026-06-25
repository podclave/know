# know Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `know` explicitly user-curated (model proposes, user approves), drop the background auto-capture, and lighten stand-up by removing the API-key ceremony, the `/wake` HTTP heartbeat, and any chance of the operator's git identity authoring KB commits.

**Architecture:** Two surfaces. The **client plugin** loses its background distiller and gains a tiny `UserPromptSubmit` nudge hook plus a `/know:commit` command — the live model proposes candidate facts and the user approves before anything is saved. The **server** re-frames the `save` tool as user-gated, replaces the `/wake` HTTP route with a one-shot `wake.py` CLI run by a scheduler, stops requiring/managing Anthropic credentials (it just expects `claude` to work on the box), and pins the KB repo's local git identity so the operator's synced global gitconfig can never author commits.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, pytest, the Claude Agent SDK (bundled CLI), bash installer, stdlib-only Claude Code hook scripts, git.

## Global Constraints

- **Client hook scripts are stdlib-only** — no third-party imports (they run under the user's bare `python3`). Copied verbatim from the existing `capture.py` constraint.
- **Server tests run with no git and no `claude`** where possible — fake handlers / fixture repos, mirroring `test_mcp_endpoint.py` and `test_app.py`.
- **SDK bundled-CLI floor is `2.1.92`** (`CLAUDE_FLOOR` in `install-know.sh`).
- **Default model id is `claude-haiku-4-5-20251001`** (`config._DEFAULT_MODEL`).
- **Reserved bot git identities are fixed:** `know-capture <capture@know.local>`, `know-secretary <secretary@know.local>` (`config.py:29-31`); the secretary's classifier keys on these exact emails — do not rename them.
- **The two installer test seams stay green:** `bash server/test-install-know.sh` (KB/remote logic via `KNOW_SETUP_TEST=1`) and `cd server/gateway && .venv/bin/python -m pytest -q`.
- **Commits frequently**, one per task minimum; never commit on a failing test.

---

### Task 1: Re-frame the `save` MCP tool as user-gated (server)

**Files:**
- Modify: `server/gateway/mcp_endpoint.py:58-74` (the `save` tool `_t(...)` description)
- Test: `server/gateway/test_mcp_endpoint.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no signature change — `save`'s `inputSchema` (title/body/type/tags/source) is unchanged. Only the human-readable `description` string changes.

- [ ] **Step 1: Write the failing test**

Add to `server/gateway/test_mcp_endpoint.py`:

```python
def test_save_description_is_user_gated(harness):
    client, _ = harness
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    save = next(t for t in tools if t["name"] == "save")
    desc = save["description"].lower()
    assert "approved" in desc
    assert "without being asked" not in desc
    assert "on your own initiative" in desc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/gateway && .venv/bin/python -m pytest test_mcp_endpoint.py::test_save_description_is_user_gated -v`
Expected: FAIL (current description contains "WITHOUT being asked", not "approved").

- [ ] **Step 3: Replace the `save` description**

In `server/gateway/mcp_endpoint.py`, replace the `save` `_t(...)` description string (lines 59-67, the text between `_t("save",` and the `{"title": ...}` properties dict) with:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd server/gateway && .venv/bin/python -m pytest test_mcp_endpoint.py -q`
Expected: PASS (new test + all existing transport tests, including `test_tools_list_is_the_full_surface`).

- [ ] **Step 5: Commit**

```bash
git add server/gateway/mcp_endpoint.py server/gateway/test_mcp_endpoint.py
git commit -m "save tool: re-frame as user-gated (propose, wait for approval)"
```

---

### Task 2: Replace background auto-capture with a nudge hook (client)

**Files:**
- Delete: `client-plugin/capture.py`, `client-plugin/scrub.py`
- Create: `client-plugin/nudge.py`
- Modify: `client-plugin/hooks/hooks.json`
- Create: `client-plugin/test_nudge.py`

**Interfaces:**
- Consumes: the Claude Code `UserPromptSubmit` hook stdin JSON (`{"transcript_path": str, "session_id": str, "prompt": str, ...}`). Stdout on exit 0 is injected into the turn's context.
- Produces: `nudge.should_nudge(lines: list[str], min_turns: int, gap_turns: int) -> bool` and `nudge.MARKER` (the literal `"<know-nudge>"`), used by the tests and by any later tooling.

- [ ] **Step 1: Write the failing test**

Create `client-plugin/test_nudge.py`:

```python
"""Unit tests for the commit-nudge hook logic. Stdlib + pytest only."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import nudge  # noqa: E402


def _user(text):
    return json.dumps({"type": "user", "message": {"content": text}})


def _assistant_save(title="X"):
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "save", "input": {"title": title}}]}})


def _meta_context(text):
    return json.dumps({"type": "user", "isMeta": True, "message": {"content": text}})


def test_no_nudge_before_min_turns():
    lines = [_user("hi"), _user("again"), _user("third")]
    assert nudge.should_nudge(lines, min_turns=6, gap_turns=8) is False


def test_nudge_after_min_turns():
    lines = [_user(f"turn {i}") for i in range(6)]
    assert nudge.should_nudge(lines, min_turns=6, gap_turns=8) is True


def test_suppressed_after_save():
    lines = [_user(f"turn {i}") for i in range(6)] + [_assistant_save()]
    assert nudge.should_nudge(lines, min_turns=6, gap_turns=8) is False


def test_marker_resets_spacing_gap():
    after_marker = [nudge.NUDGE] + [_user(f"t{i}") for i in range(3)]
    assert nudge.should_nudge(after_marker, min_turns=6, gap_turns=8) is False
    after_marker2 = [nudge.NUDGE] + [_user(f"t{i}") for i in range(8)]
    assert nudge.should_nudge(after_marker2, min_turns=6, gap_turns=8) is True


def test_meta_context_lines_are_not_user_turns():
    lines = [_meta_context("injected") for _ in range(6)]
    assert nudge.should_nudge(lines, min_turns=6, gap_turns=8) is False


def test_main_disabled_by_env(monkeypatch, tmp_path, capsys):
    tr = tmp_path / "t.jsonl"
    tr.write_text("\n".join(_user(f"t{i}") for i in range(6)))
    monkeypatch.setenv("KNOW_NUDGE", "0")
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"transcript_path": str(tr)})))
    nudge.main()
    assert capsys.readouterr().out == ""


def test_main_emits_nudge_when_due(monkeypatch, tmp_path, capsys):
    tr = tmp_path / "t.jsonl"
    tr.write_text("\n".join(_user(f"t{i}") for i in range(6)))
    monkeypatch.delenv("KNOW_NUDGE", raising=False)
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps({"transcript_path": str(tr)})))
    nudge.main()
    assert nudge.MARKER in capsys.readouterr().out


def test_main_fails_open_on_bad_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _Stdin("not json"))
    nudge.main()  # must not raise
    assert capsys.readouterr().out == ""


class _Stdin:
    def __init__(self, data): self._data = data
    def read(self): return self._data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd client-plugin && python3 -m pytest test_nudge.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nudge'`.

- [ ] **Step 3: Write `client-plugin/nudge.py`**

```python
#!/usr/bin/env python3
"""know commit-nudge — a tiny UserPromptSubmit hook (stdlib only).

It NEVER saves anything. When a session has accrued substance and nothing has been
committed to the team brain recently, it injects a short reminder (printed to stdout,
which a UserPromptSubmit hook adds to the turn's context) so the live model can PROPOSE
candidate facts the user then curates. State is read from the transcript — no state
files. Replaces the old background distiller (capture.py): the live model is a better
distiller and already holds the conversation.

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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd client-plugin && python3 -m pytest test_nudge.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Rewrite the hooks manifest**

Replace the entire contents of `client-plugin/hooks/hooks.json` with:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/nudge.py\"" } ] }
    ]
  }
}
```

- [ ] **Step 6: Delete the background distiller and its client scrub**

```bash
git rm client-plugin/capture.py client-plugin/scrub.py
```

(Confirmed safe: `server/gateway/store.py:148-158` scrubs title/body/tags/source server-side on every `save`, so model-proposed saves are scrubbed regardless of client.)

- [ ] **Step 7: Verify nothing else references the deleted files**

Run: `grep -rn "capture\.py\|import scrub\|scrub(" client-plugin/ || echo "clean"`
Expected: `clean` (the only remaining `capture`/`scrub` mentions, if any, are in this plan or server-side `gateway/scrub.py`, which is untouched).

- [ ] **Step 8: Commit**

```bash
git add client-plugin/nudge.py client-plugin/test_nudge.py client-plugin/hooks/hooks.json
git commit -m "client: replace background auto-capture with a UserPromptSubmit nudge hook"
```

---

### Task 3: Add the `/know:commit` command (client)

**Files:**
- Create: `client-plugin/commands/commit.md`
- Modify: `client-plugin/commands/setup.md:9` (mention the new command in the reminder line)

**Interfaces:**
- Consumes: the `save` MCP tool (re-framed in Task 1).
- Produces: a user-invokable `/know:commit` slash command — the on-demand counterpart to the nudge.

- [ ] **Step 1: Create the command**

Create `client-plugin/commands/commit.md`:

```markdown
---
description: Review this conversation for durable team facts and save the ones you approve
argument-hint: [optional focus — a topic to scope the scan]
---
Help me commit durable learnings from this conversation to the team **know** brain$ARGUMENTS.

1. **Scan this conversation** for statements that are durable, specific, and
   true-for-now — decisions reached, conventions, infra/architecture details
   (services, endpoints, owners, versions, ports), and gotchas/known-issues,
   INCLUDING facts surfaced while troubleshooting. Skip the ephemeral (status
   chatter, options merely proposed, anything stale next week) and never propose
   secrets/tokens/keys.
2. **Show me the candidates as a numbered list** — each a short title plus the
   self-contained fact, and (if known) where it came from. Keep it tight; one fact
   per item.
3. **Wait for my pick.** I'll say which numbers to save (and may edit them). Do NOT
   save anything I haven't explicitly approved.
4. **Save each approved fact** with the `save` tool — one call per fact, with a precise
   `title`, a self-contained `body`, and a `type`/`tags`/`source` where they help. The
   server-side secretary then dedupes, organizes, and cross-links them.

If nothing in the conversation is durable, tell me plainly — don't manufacture facts.
```

- [ ] **Step 2: Update the setup reminder to list the command**

In `client-plugin/commands/setup.md`, line 9 currently reads:

```
Then briefly remind me of what's available: the tools `recall`, `save`, `list`, `supersede`, `contradictions`, `resolve`, and the `/know:recall`, `/know:ingest`, `/know:contradictions`, `/know:resolve` commands.
```

Replace it with:

```
Then briefly remind me of what's available: the tools `recall`, `save`, `list`, `supersede`, `contradictions`, `resolve`, and the `/know:recall`, `/know:commit`, `/know:ingest`, `/know:contradictions`, `/know:resolve` commands. Note that I save durable facts only after you approve them (the model proposes, I pick) — and that it will occasionally nudge me to commit learnings when a session has built some up.
```

- [ ] **Step 3: Verify the command file is well-formed**

Run: `head -4 client-plugin/commands/commit.md`
Expected: shows the YAML frontmatter with `description:` and `argument-hint:`.

- [ ] **Step 4: Commit**

```bash
git add client-plugin/commands/commit.md client-plugin/commands/setup.md
git commit -m "client: add /know:commit (on-demand propose-and-curate)"
```

---

### Task 4: Replace `/wake` with a `wake.py` CLI (server)

**Files:**
- Create: `server/gateway/wake.py`
- Modify: `server/gateway/app.py` (remove the `/wake` route, `_alert`, `_last_secretary_age`, and the now-unused `auth_probe` import; factor the mirror-pull + reconcile so both `app.py` and `wake.py` use it)
- Modify: `server/gateway/test_app.py` (drop `test_wake_includes_kb_snapshot`)
- Create: `server/gateway/test_wake.py`

**Interfaces:**
- Consumes: `secretary.run_pass(repo) -> dict`, `kb_stats.kb_snapshot(repo) -> dict`, `store._git`, `config.MIRROR_REMOTE`, `config.SECRETARY_IDENTITY`, `config.NAME`.
- Produces: `wake.wake(repo: Path) -> dict` (the one-shot heartbeat: pull mirror, reconcile if it moved, report liveness/inventory; alerts on a failed reconcile) and `wake.main()` (CLI entrypoint, prints the dict as JSON).

- [ ] **Step 1: Write the failing test**

Create `server/gateway/test_wake.py`:

```python
"""wake.py CLI — mirror-pull + reconcile + liveness, against a fake repo. No agent."""
from unittest.mock import patch

import wake


def _snapshot(_repo):
    return {"curated_facts": 1, "raw_backlog": 0, "open_contradictions": 0,
            "secretary_behind": False}


def test_wake_reports_inventory_when_no_mirror(tmp_path):
    # no 'mirror' remote configured -> no pull, no reconcile, just liveness
    with patch("wake._git") as g, \
         patch("wake.kb_snapshot", _snapshot), \
         patch("wake._last_secretary_age", return_value=12.0):
        g.return_value.stdout = ""          # `git remote` lists nothing
        out = wake.wake(tmp_path)
    assert out["mirror"] == "no remote"
    assert out["curated_facts"] == 1
    assert out["last_curation_secs_ago"] == 12


def test_wake_reconciles_when_mirror_moves(tmp_path):
    seq = {"n": 0}

    def fake_git(repo, *args, **kw):
        m = type("R", (), {"stdout": ""})()
        if args[:1] == ("remote",):
            m.stdout = "mirror\n"
        elif args[:1] == ("rev-parse",):
            seq["n"] += 1
            m.stdout = "AAAA" if seq["n"] == 1 else "BBBB"   # HEAD moved after pull
        return m

    with patch("wake._git", side_effect=fake_git), \
         patch("wake.kb_snapshot", _snapshot), \
         patch("wake._last_secretary_age", return_value=0.0), \
         patch("wake.run_pass", return_value={"status": "committed"}) as rp:
        out = wake.wake(tmp_path)
    rp.assert_called_once()
    assert out["mirror"] == "pulled new commits"
    assert out["reconcile"] == "committed"


def test_wake_alerts_on_failed_reconcile(tmp_path):
    def fake_git(repo, *args, **kw):
        m = type("R", (), {"stdout": ""})()
        if args[:1] == ("remote",):
            m.stdout = "mirror\n"
        elif args[:1] == ("rev-parse",):
            m.stdout = "AAAA" if fake_git.calls == 0 else "BBBB"
            fake_git.calls += 1
        return m
    fake_git.calls = 0

    with patch("wake._git", side_effect=fake_git), \
         patch("wake.kb_snapshot", _snapshot), \
         patch("wake._last_secretary_age", return_value=0.0), \
         patch("wake.run_pass", return_value={"status": "error", "error": "boom"}), \
         patch("wake._alert") as alert:
        out = wake.wake(tmp_path)
    assert out["reconcile"] == "error"
    alert.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server/gateway && .venv/bin/python -m pytest test_wake.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wake'`.

- [ ] **Step 3: Write `server/gateway/wake.py`**

```python
#!/usr/bin/env python3
"""know wake — the one-shot heartbeat, run by a scheduler instead of an HTTP route.

Replaces the old /wake endpoint + external HTTP pinger. A Podclave Schedule (on a
Sprite) or a crontab line (on a plain VM) runs this hourly:
  python wake.py
It does the one thing the live box can't see — an off-box mirror push — by pulling the
mirror remote and, if it moved, running a reconcile curation pass. It also reports
curator liveness + KB inventory, and alerts (KNOW_ALERT_WEBHOOK) if a reconcile errors.

`know` makes no claims about auth: there is no separate credential probe. If the agent
can't run, the reconcile pass surfaces it as an error here (and alerts); routine saves
and recalls surface it as a loud tool error. Make sure `claude` works on this box.
"""
import json
import os
import sys
import time

import httpx

import config
from kb_stats import kb_snapshot
from secretary import run_pass
from store import _git


def _last_secretary_age(repo) -> float | None:
    """Seconds since the last secretary commit (curator liveness), or None."""
    out = _git(repo, "log", "--format=%ct", f"--author={config.SECRETARY_IDENTITY[1]}",
               "-1", check=False).stdout.strip()
    return (time.time() - float(out)) if out else None


def _alert(text: str) -> None:
    """Best-effort out-of-band alert (Slack webhook) — no-op without KNOW_ALERT_WEBHOOK."""
    hook = (os.environ.get("KNOW_ALERT_WEBHOOK") or "").strip()
    if not hook:
        return
    try:
        httpx.post(hook, json={"text": f"[know:{config.NAME}] {text}"}, timeout=10)
    except Exception:
        pass


def wake(repo) -> dict:
    out = {"name": config.NAME, "woke": time.time()}
    # pull the mirror (the one event the box can't see) + reconcile if it moved
    try:
        remotes = _git(repo, "remote", check=False).stdout.split()
        if config.MIRROR_REMOTE in remotes:
            before = _git(repo, "rev-parse", "HEAD", check=False).stdout.strip()
            _git(repo, "pull", "--ff-only", config.MIRROR_REMOTE, check=False)
            after = _git(repo, "rev-parse", "HEAD", check=False).stdout.strip()
            if before != after:
                out["mirror"] = "pulled new commits"
                res = run_pass(repo)
                status = res.get("status") if isinstance(res, dict) else "unknown"
                out["reconcile"] = status
                if status not in ("committed", "noop", "nothing", "clean"):
                    _alert(f"reconcile failed: {res}")
            else:
                out["mirror"] = "up to date"
        else:
            out["mirror"] = "no remote"
    except Exception as e:  # noqa: BLE001
        out["mirror_error"] = str(e)
        _alert(f"wake error: {e}")
    # liveness + inventory
    age = _last_secretary_age(repo)
    out["last_curation_secs_ago"] = round(age) if age is not None else None
    out.update(kb_snapshot(repo))
    return out


def main():
    print(json.dumps(wake(config.KB_REPO)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> Note: `run_pass`'s success status string is `"committed"` (see `app.py:136`); the
> guard above treats `committed` and common no-op spellings as success and alerts on
> anything else. If `run_pass` returns a different no-op string, widen the tuple — do
> not narrow it to only `committed`, or a clean no-op pass would false-alarm.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `cd server/gateway && .venv/bin/python -m pytest test_wake.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Remove `/wake` and its now-unused helpers from `app.py`**

In `server/gateway/app.py`:
- Delete the `@app.post("/wake")` / `@app.get("/wake")` route and its `wake()` function (lines 225-259).
- Delete `_alert` (lines 205-215) and `_last_secretary_age` (lines 218-222) — they now live in `wake.py`.
- In the imports, change `from boot_check import auth_probe` — **remove this line** (`/wake` was its only user). Keep all other imports.

Verify no remaining references:

Run: `grep -n "auth_probe\|/wake\|_alert\|_last_secretary_age" server/gateway/app.py || echo clean`
Expected: `clean`.

Then check whether `import os` is now unused in `app.py` (it was used only by `_alert`):

Run: `grep -n "os\." server/gateway/app.py || echo "os unused"`
If it prints `os unused`, remove the `import os` line from `app.py`.

- [ ] **Step 6: Drop the obsolete `/wake` app test**

In `server/gateway/test_app.py`, delete `test_wake_includes_kb_snapshot` (lines 37-47) and the now-unused `from unittest.mock import patch` import if nothing else uses it (it isn't used elsewhere in the file — remove it).

- [ ] **Step 7: Run the full server suite**

Run: `cd server/gateway && .venv/bin/python -m pytest -q`
Expected: PASS (all suites, including `test_wake.py` and the trimmed `test_app.py`).

- [ ] **Step 8: Commit**

```bash
git add server/gateway/wake.py server/gateway/test_wake.py server/gateway/app.py server/gateway/test_app.py
git commit -m "server: replace /wake HTTP route with a one-shot wake.py CLI"
```

---

### Task 5: Stop requiring/managing Anthropic credentials (server)

**Files:**
- Modify: `server/gateway/boot_check.py` (remove the REST `x-api-key` auth probe + REST model-resolution; keep only the credential-free SDK-version checks)
- Modify: `server/gateway/recall.py:57-63` (de-key the auth-failure message)
- Modify: `server/gateway/test_boot_check.py` (drop the REST/auth/model tests)

**Interfaces:**
- Consumes: `boot_check.sdk_cli_version()`, `boot_check.version_ok(floor, recorded=None)` (unchanged).
- Produces: `boot_check.full_check(floor, recorded=None) -> int` — now a **runtime-only** check (SDK bundled-CLI floor + recorded-version match); no auth, no model-resolution. `auth_probe`, `list_models`, `model_resolves`, `resolve_cheapest_haiku`, `_headers` are **removed**.

- [ ] **Step 1: Update the boot-check tests to the new surface**

Replace the entire contents of `server/gateway/test_boot_check.py` with:

```python
"""Boot-check helpers — credential-free SDK-runtime checks only.

`know` makes no claims about auth (it just expects `claude` to work on the box), so the
REST x-api-key auth probe and REST model-resolution were removed. The real auth+model
validation is the install-time save+recall smoke test, which warns (does not die)."""
from unittest.mock import patch

import boot_check


def test_version_ok_below_floor_fails():
    with patch("boot_check.sdk_cli_version", return_value="2.0.0"):
        ok, msg = boot_check.version_ok("2.1.92")
    assert ok is False
    assert "below" in msg


def test_version_ok_at_floor_passes():
    with patch("boot_check.sdk_cli_version", return_value="2.1.92"):
        ok, msg = boot_check.version_ok("2.1.92")
    assert ok is True
    assert msg == "2.1.92"


def test_version_ok_recorded_mismatch_fails():
    with patch("boot_check.sdk_cli_version", return_value="2.2.0"):
        ok, msg = boot_check.version_ok("2.1.92", recorded="2.1.99")
    assert ok is False
    assert "recorded" in msg


def test_full_check_passes_on_good_runtime(capsys):
    with patch("boot_check.sdk_cli_version", return_value="2.1.92"):
        rc = boot_check.full_check("2.1.92")
    assert rc == 0
    assert "agent runtime" in capsys.readouterr().out


def test_no_rest_auth_surface_remains():
    # the credential-bound REST helpers are gone
    for gone in ("auth_probe", "list_models", "model_resolves", "resolve_cheapest_haiku"):
        assert not hasattr(boot_check, gone)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server/gateway && .venv/bin/python -m pytest test_boot_check.py -q`
Expected: FAIL — `full_check` still requires a `model` arg / the removed helpers still exist.

- [ ] **Step 3: Rewrite `boot_check.py` to the credential-free surface**

Replace the entire contents of `server/gateway/boot_check.py` with:

```python
"""Boot self-check — credential-free SDK runtime checks.

`know` makes no claims about auth: it runs the Claude Agent SDK and expects `claude` to
already work on the box (whatever credential the operator has — subscription token, API
key, logged-in ~/.claude). So there is NO auth probe and NO REST model-resolution here;
the install-time save+recall smoke test is the real auth+model check, and it WARNS
rather than blocks. What remains needs no credential:
  • runtime — the SDK's bundled CLI >= floor AND matches the recorded version.

Usage:
  python boot_check.py sdk-version            -> prints the bundled CLI version
  python boot_check.py version <floor>        -> exit 0/1 (+ optional recorded)
  python boot_check.py check <floor> [recorded_ver]   -> runtime check
"""
import sys


def sdk_cli_version() -> str | None:
    """The Claude Code CLI version BUNDLED with the installed Agent SDK — the agent
    runtime recall/the secretary actually run on. Pinned by the SDK, native + Node-free,
    isolated from any system `claude`."""
    try:
        from claude_agent_sdk._cli_version import __cli_version__
        return __cli_version__
    except Exception:  # noqa: BLE001
        return None


def _ver_tuple(v: str):
    return tuple(int(x) for x in v.split("."))


def version_ok(floor: str, recorded: str | None = None) -> tuple[bool, str]:
    cur = sdk_cli_version()
    if not cur:
        return False, "could not determine the SDK's bundled CLI version (is claude-agent-sdk installed?)"
    if _ver_tuple(cur) < _ver_tuple(floor):
        return False, f"bundled CLI {cur} is below the required floor {floor} (bump claude-agent-sdk)"
    if recorded and cur != recorded:
        return False, f"bundled CLI {cur} != the recorded/pinned version {recorded} (bump the SDK pin + re-record)"
    return True, cur


def full_check(floor: str, recorded: str | None = None) -> int:
    v_ok, v_msg = version_ok(floor, recorded)
    print(f"[1/1] agent runtime ... {'OK' if v_ok else 'FAIL'} — bundled CLI {v_msg}")
    return 0 if v_ok else 1


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "sdk-version":
        v = sdk_cli_version()
        print(v or "")
        return 0 if v else 1
    if cmd == "version":
        ok, msg = version_ok(argv[1], argv[2] if len(argv) > 2 else None)
        print(msg)
        return 0 if ok else 1
    if cmd == "check":
        if len(argv) < 2:
            print("usage: check <floor> [recorded_version]")
            return 2
        return full_check(argv[1], argv[2] if len(argv) > 2 else None)
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: De-key the recall auth-failure message**

In `server/gateway/recall.py`, replace the auth-failure branch (lines 57-63):

```python
    if res.is_error:
        # Distinct, loud auth message (§5.5) vs a generic agent failure.
        if re.search(r"auth|credential|api[\s_-]?key|401|unauthor|invalid x-api|forbidden",
                     res.error, re.I):
            raise RuntimeError("brain auth invalid — the box's Claude auth is "
                               "missing/expired/over-quota; recall is down until "
                               "`claude` works on the box again")
        raise RuntimeError(f"recall agent failed: {res.error[:300]}")
```

(Only the `RuntimeError` message text changes — the regex and structure are unchanged.)

- [ ] **Step 5: Run the affected suites to verify they pass**

Run: `cd server/gateway && .venv/bin/python -m pytest test_boot_check.py test_recall.py -q`
Expected: PASS. (If `test_recall.py` asserted the old `ANTHROPIC_API_KEY` wording in the auth message, update that assertion to match the new text — search it: `grep -n "ANTHROPIC_API_KEY" test_recall.py`.)

- [ ] **Step 6: Commit**

```bash
git add server/gateway/boot_check.py server/gateway/test_boot_check.py server/gateway/recall.py server/gateway/test_recall.py
git commit -m "server: drop the API-key REST auth/model gate (no claims about auth)"
```

---

### Task 6: De-key the installer, drop `/wake` onboarding, add the commit-identity floor (server)

**Files:**
- Modify: `server/install-know.sh` (remove key requirement + service-env key; replace `resolve-model` REST with the default; simplify the boot self-check call; set the KB repo local git identity on seed AND restore; downgrade the recall smoke to a clear warn; replace the `/wake` onboarding section with the scheduled `wake` command)
- Modify: `server/test-install-know.sh` (assert the commit-identity floor)

**Interfaces:**
- Consumes: `boot_check.py check <floor> [recorded]` (Task 5), `wake.py` (Task 4), `config._DEFAULT_MODEL` semantics (the default haiku id).
- Produces: an installer that needs no `ANTHROPIC_API_KEY`, leaves no `/wake` step, and guarantees KB commits are authored by the bot identity.

- [ ] **Step 1: Add the commit-identity floor to the test harness (failing test)**

In `server/test-install-know.sh`, after the `== A: --no-remote (local-only) ==` block (which creates `$T/kbA`), add a new block:

Add this block to `server/test-install-know.sh` (after the `kbA` `--no-remote` block):

```bash
echo "== identity floor: KB repo local git config is the bot, not a global identity =="
[ "$(git -C "$T/kbA" config user.name)"  = "know-capture" ]       && ok "local user.name pinned"  || no "user.name not pinned"
[ "$(git -C "$T/kbA" config user.email)" = "capture@know.local" ] && ok "local user.email pinned" || no "user.email not pinned"
# A commit with NO -c identity must still be authored by the bot: repo-local config
# beats the (absent) global one. Empty fake HOME = no global gitconfig to fall back to,
# so this proves the floor protects the real risk (a path that forgets -c).
mkdir -p "$T/fakehome"
echo scratch > "$T/kbA/raw/floor-probe.md"; git -C "$T/kbA" add -A
HOME="$T/fakehome" GIT_CONFIG_NOSYSTEM=1 git -C "$T/kbA" commit -q -m "probe"
AUTH="$(git -C "$T/kbA" log -1 --format='%an <%ae>')"
echo "$AUTH" | grep -q "capture@know.local" && ok "no-identity commit authored by the bot ($AUTH)" || no "leaked identity: $AUTH"
```

And assert the floor also lands on the **restore-clone** path — add to the existing
`== C: existing (non-empty) remote -> RESTORE ==` block (operates on `$T/kbC`):

```bash
[ "$(git -C "$T/kbC" config user.email)" = "capture@know.local" ] && ok "restore pinned the identity floor" || no "restore left identity unpinned"
```

- [ ] **Step 2: Run the harness to verify the new asserts fail**

Run: `bash server/test-install-know.sh`
Expected: the new identity-floor asserts FAIL (the installer does not yet set repo-local `user.*`), other asserts still PASS.

- [ ] **Step 3: Set the identity floor in `_seed_kb` and the restore path**

In `server/install-know.sh`, define a helper near the other KB helpers (after `_wire_mirror`, ~line 124):

```bash
_pin_identity() {             # repo-local commit identity = the bot, NEVER the synced global
  git -C "$KB_REPO" config user.name  "know-capture"
  git -C "$KB_REPO" config user.email "capture@know.local"
}
```

Call it in `_seed_kb` (right after `git -C "$KB_REPO" init ...`, before the first commit), e.g. after line 109:

```bash
  _pin_identity
```

And call it on the restore-clone path in `setup_kb` (after the clone + remote rename, around line 194, before the `ok "restored ...` line):

```bash
  _pin_identity
```

Also call it on the reuse path (top of `setup_kb`, after `log "KB repo exists..."`, ~line 174) so a re-run on an older brain backfills the floor:

```bash
  _pin_identity
```

- [ ] **Step 4: Run the harness to verify the identity floor passes**

Run: `bash server/test-install-know.sh`
Expected: all asserts PASS (including the new identity-floor block on `kbA`, and `kbC` restore still works).

- [ ] **Step 5: Remove the API-key requirement and service-env key**

In `server/install-know.sh`:
- Delete the key-file constant `KEY_FILE=...` (line 37).
- Delete the key-resolution block (lines 239-246: `API_KEY=...` through `export ANTHROPIC_API_KEY=...`).
- In the service `ENVS` (line 300), remove `ANTHROPIC_API_KEY=$API_KEY,` so it reads:

```bash
ENVS="HOME=$HOME,PATH=$PATH,KNOW_SECRET=$SECRET,KNOW_NAME=$NAME,KNOW_MODEL=$MODEL"
```

**Do NOT re-add any credential to `ENVS`.** Auth is inherited via `HOME`: the service
runs as the operator's user with their `HOME`, so the SDK finds whatever makes
interactive `claude` work for that user — most importantly a logged-in `~/.claude`
(subscription token). This is deliberate: it rides the operator's existing auth without
`know` provisioning, prompting, or overriding it (a forwarded `ANTHROPIC_API_KEY` would
override a subscription — exactly what we're avoiding). If an operator's box auths only
via a shell env var, the install-time recall smoke warns clearly and they can add it to
the service env themselves; `know` does not do it for them. Add a short comment above
`ENVS` to this effect.

- Update the script's header comment (lines 7-10) to drop the `ANTHROPIC_API_KEY` requirement, e.g. replace line 7's "Needs: an ANTHROPIC_API_KEY (default: the sk- line of ~/ANTHROPIC_API_KEY), a Sprite" with "Needs: a working `claude` on this box (any Claude auth the SDK can use — subscription token, API key, or logged-in ~/.claude), a Sprite".

- [ ] **Step 6: Replace REST model-resolution with the default, and simplify the boot check**

In `server/install-know.sh`:
- Model resolution (lines 278-283): the third fallback used `boot_check.py resolve-model` (now removed). Replace that fallback with the default haiku id constant:

```bash
# --- 3. resolve the model id (KNOW_MODEL > existing service's pin > default haiku) --
MODEL="${KNOW_MODEL:-}"
[ -z "$MODEL" ] && MODEL="$(svc_env KNOW_MODEL)"
[ -z "$MODEL" ] && MODEL="claude-haiku-4-5-20251001"
ok "model: $MODEL (override with KNOW_MODEL=<id>)"
```

- Boot self-check (lines 327-330): `boot_check.py check` no longer takes a model arg. Replace with:

```bash
# --- 8. boot self-check: agent RUNTIME only (no auth/model gate — see §smoke below) --
log "checking the agent runtime (SDK bundled CLI)..."
"$PYBIN" "$GW_DIR/boot_check.py" check "$CLAUDE_FLOOR" "$CLAUDE_VER" \
  || die "agent runtime check FAILED — the SDK's bundled CLI is missing or below floor"
```

- [ ] **Step 7: Downgrade the recall smoke to a clear, non-fatal warning**

In `server/install-know.sh`, the recall smoke (line 356) already only warns on a miss. Make the message actionable about auth, since this is now the real auth+model check. Replace line 356 with:

```bash
echo "$recall_out" | grep -qi 'canary' \
  || log "WARN: recall did not surface the canary — the agent may not be able to run.
  Make sure \`claude\` works on this box (any Claude auth the SDK can use) and that the
  model '$MODEL' is available; saves still work, but recall/curation need a working agent.
  raw: $(echo "$recall_out" | head -c 200)"
```

(The `save` smoke at lines 350-352 stays a hard `die` — it exercises the pure git store, which needs no auth; a failure there is a real bug, not an auth issue.)

- [ ] **Step 8: Replace the `/wake` onboarding section with the scheduled command**

In `server/install-know.sh`, replace the Heartbeat block in the onboarding card (lines 418-424) with:

```bash
  Heartbeat (off-box reconcile): a spun-down box can't cron itself, so schedule this
  command to run hourly — it pulls the mirror remote and reconciles any off-box edits:

      $PYBIN $GW_DIR/wake.py

  • Sprite: create a Podclave Schedule (control plane) that runs the command above hourly.
  • Plain VM: add a crontab line, e.g.  0 * * * * $PYBIN $GW_DIR/wake.py
  (Only needed if you edit the KB off-box via the mirror remote; with --no-remote it's
  a no-op. There is no /wake HTTP endpoint anymore.)
```

- [ ] **Step 9: Run both regression suites**

Run: `bash server/test-install-know.sh && cd server/gateway && .venv/bin/python -m pytest -q`
Expected: both PASS. (The install harness uses the `KNOW_SETUP_TEST` seam, which exits before the service/key/boot-check sections, so it exercises the KB + identity-floor logic without needing a key.)

- [ ] **Step 10: Lint the installer**

Run: `bash -n server/install-know.sh && echo "syntax ok"`
Expected: `syntax ok`.

- [ ] **Step 11: Commit**

```bash
git add server/install-know.sh server/test-install-know.sh
git commit -m "installer: no API-key ceremony, no /wake step, pin KB commit identity floor"
```

---

### Task 7: Update docs and the non-Sprite examples (docs)

**Files:**
- Modify: `README.md` (auth line, `/wake` / pinger sections, capture section, connect command list, onboarding mentions)
- Modify: `docs/DEVELOPING.md` (`/wake`, API-key-scoping, capture references)
- Modify: `server/kb-template/CLAUDE.md:108` (the `/wake` reconcile mention)
- Modify: `server/know-gateway.service.example` (drop the API-key env + `/wake` pinger note)
- Delete: `examples/github-actions-wake.yml`
- Modify: `client-plugin/.claude-plugin/plugin.json` (description: capture → nudge; bump version)

**Interfaces:**
- Consumes: the behavior shipped in Tasks 1-6.
- Produces: docs consistent with the new design (no automated test; verified by grep).

- [ ] **Step 1: Update the systemd example**

In `server/know-gateway.service.example`:
- Delete line 6 (`# Pair with an external /wake pinger ...`) and replace with:
  `# Schedule the heartbeat (off-box reconcile) hourly via cron, e.g.:`
  `#   0 * * * * /home/know/know-gateway/.venv/bin/python /home/know/know-gateway/wake.py`
- Delete line 18 (`Environment=ANTHROPIC_API_KEY_FILE=...`) — the service inherits whatever Claude auth works for the `know` user; add a comment:
  `# No API key here — the service inherits the box's Claude auth (whatever makes`
  `# interactive \`claude\` work for this user: subscription token, API key, or ~/.claude).`

- [ ] **Step 2: Remove the GitHub Actions pinger example**

```bash
git rm examples/github-actions-wake.yml
```

- [ ] **Step 3: Update the kb-template reconcile note**

In `server/kb-template/CLAUDE.md`, line 108 references reconcile "via `/wake`". Replace `/wake` with "the scheduled `wake` heartbeat" so it reads, e.g.: "the next pass after you push (via the scheduled `wake` heartbeat) — there's no curator in your clone."

- [ ] **Step 4: Update README.md**

Apply these edits to `README.md`:
- **Auth bullet (line 43):** replace "The brain authenticates to Anthropic with a static API key, scoped to the service only." with: "The brain runs the Claude Agent SDK and uses whatever Claude auth already works on the box — it makes no claims about auth and provisions nothing. Running a server agent on a personal subscription is technically fine but against the spirit of subscription auth; choose with eyes open."
- **Architecture diagram (lines 22-23):** change the `external pinger (hourly) ──poke──▶ <brain>/wake` line to: `scheduled wake (hourly) ──run──▶  wake.py  (pull mirror · reconcile off-box edits)`.
- **Install section (lines 57-58):** drop the `ANTHROPIC_API_KEY` precondition; state the precondition is a working `claude` on the box.
- **Boot self-check description (lines 76-79):** change "ordered boot self-check (auth → agent runtime → model-resolves ...)" to "agent-runtime check (SDK bundled CLI) plus a real save+recall smoke (which warns, not dies, if the agent can't run)".
- **Env line (line 88):** remove `ANTHROPIC_API_KEY (or its _FILE)`; keep `KNOW_MODEL` and `KNOW_ALERT_WEBHOOK`.
- **"Keeping it alive" section (lines 173-179):** rewrite to describe the scheduled `wake.py` command (Podclave Schedule on Sprite / crontab on a VM) instead of the `/wake` HTTP pinger; state there is no `/wake` endpoint.
- **"Passive capture" section (lines 181-186):** replace it with a "Commit learnings (the nudge)" section: the plugin ships a `UserPromptSubmit` nudge that, when a session has built up durable facts, prompts Claude to propose them for you to approve — nothing is saved without your yes — plus the `/know:commit` command to do it on demand. Tunables: `KNOW_NUDGE=0` to disable, `KNOW_NUDGE_MIN_TURNS`, `KNOW_NUDGE_GAP_TURNS`.
- **Connect command lists (lines 117, 154):** add `/know:commit` to the listed commands.
- **Security note (line 43 area / lines 197-204):** unchanged (still accurate).

- [ ] **Step 5: Update DEVELOPING.md**

In `docs/DEVELOPING.md`:
- Line 7, 41-42, 78: replace `/wake` references with "the scheduled `wake.py` heartbeat".
- Lines 141-142: the "Scope the API key to the service" guidance is obsolete — replace with: "`know` provisions no credential — it inherits the box's working Claude auth. Keep the service's environment minimal; do not bake an API key into it."
- Line 161: update the off-box reconcile path to reference the scheduled `wake` command rather than a webhook → `/wake`.
- Add a one-line mention of `wake.py` and `nudge.py` (client) to the module list near `app.py`.

- [ ] **Step 6: Update the plugin manifest**

In `client-plugin/.claude-plugin/plugin.json`:
- In `description`, change "with optional passive capture" → "with an opt-out nudge to commit learnings you approve", and "Bundles the MCP connector + /know:* commands" stays.
- Bump `version` from `0.3.0` to `0.4.0`.

- [ ] **Step 7: Verify no stale references remain**

Run:
```bash
cd /home/sprite/know/.claude/worktrees/know-simplification
grep -rn "/wake\|ANTHROPIC_API_KEY\|passive capture\|capture\.py\|github-actions-wake" README.md docs/ server/ client-plugin/ \
  | grep -v "docs/superpowers/" | grep -v "gateway/scrub.py" || echo "clean"
```
Expected: `clean` (any remaining hits should be intentional — e.g. a historical note — and reviewed by hand).

- [ ] **Step 8: Commit**

```bash
git add README.md docs/DEVELOPING.md server/kb-template/CLAUDE.md server/know-gateway.service.example client-plugin/.claude-plugin/plugin.json
git commit -m "docs: align with user-curated saves, scheduled wake, and no-key stand-up"
```

---

## Final verification (run after all tasks)

- [ ] **Server suite:** `cd server/gateway && .venv/bin/python -m pytest -q` → all PASS.
- [ ] **Client nudge suite:** `cd client-plugin && python3 -m pytest test_nudge.py -q` → all PASS.
- [ ] **Installer regression:** `bash server/test-install-know.sh` → all PASS.
- [ ] **Installer syntax:** `bash -n server/install-know.sh` → ok.
- [ ] **Wire client tests into CI:** in `.github/workflows/test.yml`, add a step under the `gateway` job (or a new job) that runs `cd client-plugin && python3 -m pytest test_nudge.py -q`, so the nudge logic is covered on every push. Commit separately:

```bash
git add .github/workflows/test.yml
git commit -m "CI: run the client nudge-hook tests"
```

## Notes / decisions locked in this plan

- **No `/wake` deprecation shim.** Clean removal; an old external pinger hitting `/wake` simply gets a 404 (harmless) until the operator switches to the scheduled command. (Spec left this open; decided here.)
- **Nudge thresholds:** `KNOW_NUDGE_MIN_TURNS=6`, `KNOW_NUDGE_GAP_TURNS=8`, `KNOW_NUDGE=1` (on). All env-tunable. (Spec left these open; defaults chosen here.)
- **Marker-in-transcript detection** assumes Claude Code persists injected `UserPromptSubmit` context (containing `<know-nudge>`) into the transcript JSONL. If, during the integration smoke, it turns out injected context is *not* persisted, the minimal fallback is a per-session marker file written by `nudge.py` — but try the transcript path first (it keeps the "no state files" property). Verify by running a real session and grepping the transcript for `<know-nudge>`.
- **Auth alerting tradeoff:** there is no longer a proactive hourly auth probe. Auth problems surface as a loud tool error on the next real `recall`/`save`/reconcile, and `wake.py` alerts on a failed reconcile. This is intentional under "no claims about auth".
