"""Store tests — save/list/supersede round-trip through a real temp git repo, with
scrub-on-write and bot-identity attribution. No claude, no network."""
import subprocess

import pytest

import config
from store import GitStore, parse_md, render_md


@pytest.fixture()
def store(tmp_path):
    s = GitStore(tmp_path / "kb")
    s.ensure_layout()
    return s


def _log_authors(repo):
    out = subprocess.run(["git", "-C", str(repo), "log", "--format=%ae"],
                         capture_output=True, text=True).stdout.split()
    return out


def test_save_writes_raw_file_committed_as_capture(store):
    r = store.save("Our gateway is Kong", "We front all traffic with Kong.",
                   attribution="alice")
    assert r["status"] == "saved"
    f = store.repo / r["path"]
    assert f.exists() and f.parent.name == "raw"
    meta, body = parse_md(f.read_text())
    assert meta["title"] == "Our gateway is Kong"
    assert meta["author"] == "alice"
    assert meta["id"] == r["id"]
    assert "Kong" in body
    # committed under the reserved capture identity (the classifier keys on this)
    assert _log_authors(store.repo)[0] == config.CAPTURE_IDENTITY[1]


def test_save_scrubs_secrets(store):
    r = store.save("API key note",
                   "The key is sk-ant-api03-AAAABBBBCCCCDDDDEEEE and ghp_ABCDEFGHIJKLMNOPQRST1234",
                   attribution="bob")
    body = (store.repo / r["path"]).read_text()
    assert "sk-ant-api03" not in body
    assert "ghp_ABCDEFG" not in body
    assert "[REDACTED]" in body


def test_save_empty_body_raises(store):
    with pytest.raises(ValueError):
        store.save("title", "   ", attribution="x")


def test_list_returns_saved_facts(store):
    store.save("Alpha fact", "body a", aliases=["a1"], attribution="alice")
    store.save("Beta fact", "body b", attribution="bob")
    r = store.list()
    assert r["count"] == 2
    titles = {f["title"] for f in r["facts"]}
    assert titles == {"Alpha fact", "Beta fact"}
    assert all(f["status"] == "raw" for f in r["facts"])


def test_list_filter_matches_title_and_aliases(store):
    store.save("Gateway config", "x", aliases=["kong"], attribution="a")
    store.save("Database choice", "y", attribution="a")
    assert {f["title"] for f in store.list("gateway")["facts"]} == {"Gateway config"}
    assert {f["title"] for f in store.list("kong")["facts"]} == {"Gateway config"}  # alias hit
    assert {f["title"] for f in store.list("database")["facts"]} == {"Database choice"}


def test_supersede_moves_to_superseded_never_deletes(store):
    saved = store.save("Old fact", "this is outdated", attribution="alice")
    fid = saved["id"]
    r = store.supersede(fid, by="some new fact", attribution="bob")
    assert r["status"] == "superseded"
    # gone from raw/, present in _superseded/
    assert not (store.repo / saved["path"]).exists()
    moved = list((store.repo / "_superseded").glob("*.md"))
    assert len(moved) == 1
    assert "outdated" in moved[0].read_text()
    # no longer listed
    assert store.list()["count"] == 0


def test_supersede_unknown_id_raises(store):
    with pytest.raises(ValueError):
        store.supersede("notreal")


def test_render_parse_roundtrip():
    meta = {"id": "ab12", "title": "T", "author": "x", "surface": "mcp",
            "date": "2026-06-17T00:00:00Z", "aliases": ["one", "two"], "source": "doc"}
    text = render_md(meta, "the body\n\nmore")
    m2, body = parse_md(text)
    assert m2["id"] == "ab12" and m2["title"] == "T"
    assert m2["aliases"] == ["one", "two"]
    assert body.strip() == "the body\n\nmore"
