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
