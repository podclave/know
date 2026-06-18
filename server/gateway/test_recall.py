"""Recall observables — deterministic §5.5 behavior with a faked agent (no network)."""
import asyncio

import pytest

from agent import AgentResult
import recall as recall_mod


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "kb"
    for sub in ("raw", "curated", "_superseded", "contradictions"):
        (r / sub).mkdir(parents=True)
    return r


def _patch_collect(monkeypatch, result: AgentResult):
    async def fake_collect(*_a, **_kw):
        return result
    monkeypatch.setattr(recall_mod, "collect", fake_collect)


def test_empty_brain_is_honest_not_a_failed_lookup(repo, monkeypatch):
    _patch_collect(monkeypatch, AgentResult())
    out = asyncio.run(recall_mod.recall("anything", repo=repo))
    assert "empty brain" in out.lower()
    assert "not a failed lookup" in out.lower()


def test_auth_failure_raises_loud_message(repo, monkeypatch):
    (repo / "curated" / "fact.md").write_text("---\ntype: Fact\ntitle: X\n---\nbody\n")
    err = AgentResult(is_error=True, error="401 Unauthorized: invalid x-api-key")
    _patch_collect(monkeypatch, err)
    with pytest.raises(RuntimeError, match="brain auth invalid"):
        asyncio.run(recall_mod.recall("x", repo=repo))


def test_generic_agent_failure_is_distinct_from_auth(repo, monkeypatch):
    (repo / "curated" / "fact.md").write_text("---\ntype: Fact\ntitle: X\n---\nbody\n")
    err = AgentResult(is_error=True, error="something else went wrong")
    _patch_collect(monkeypatch, err)
    with pytest.raises(RuntimeError, match="recall agent failed"):
        asyncio.run(recall_mod.recall("x", repo=repo))


def test_secretary_behind_signal_appended(repo, monkeypatch):
    (repo / "curated" / "one.md").write_text("---\ntype: Fact\ntitle: One\n---\n1\n")
    for i in range(8):
        (repo / "raw" / f"r{i}.md").write_text(f"---\ntype: Fact\ntitle: R{i}\n---\nraw\n")
    _patch_collect(monkeypatch, AgentResult(text="found one fact"))
    out = asyncio.run(recall_mod.recall("kong", repo=repo))
    assert "recall signal" in out
    assert "secretary may be behind" in out


def test_no_signal_when_backlog_is_small(repo, monkeypatch):
    (repo / "curated" / "a.md").write_text("---\ntype: Fact\ntitle: A\n---\na\n")
    (repo / "curated" / "b.md").write_text("---\ntype: Fact\ntitle: B\n---\nb\n")
    (repo / "raw" / "r.md").write_text("---\ntype: Fact\ntitle: R\n---\nr\n")
    _patch_collect(monkeypatch, AgentResult(text="found facts"))
    out = asyncio.run(recall_mod.recall("a", repo=repo))
    assert "recall signal" not in out


def test_agent_empty_text_gets_plain_no_facts_fallback(repo, monkeypatch):
    (repo / "curated" / "fact.md").write_text("---\ntype: Fact\ntitle: X\n---\nbody\n")
    _patch_collect(monkeypatch, AgentResult(text=""))
    out = asyncio.run(recall_mod.recall("missing", repo=repo))
    assert "No relevant facts found" in out
