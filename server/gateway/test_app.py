"""App endpoint tests — healthz inventory (no agent, no network)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import app as know_app
from store import GitStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    monkeypatch.setattr(config, "KB_REPO", kb)
    monkeypatch.setattr(know_app, "KB_REPO", kb)
    monkeypatch.setattr(know_app, "CURATE", {"writes": 0, "last_run": 0.0, "scheduled": False})
    GitStore(kb).ensure_layout()
    return TestClient(know_app.app)


def test_healthz_reports_kb_inventory(client, tmp_path):
    kb = config.KB_REPO
    (kb / "curated" / "a.md").write_text("---\ntype: Fact\ntitle: A\n---\na\n")
    (kb / "raw" / "b.md").write_text("---\ntype: Fact\ntitle: B\n---\nb\n")
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["curated_facts"] == 1
    assert body["raw_backlog"] == 1
    assert body["open_contradictions"] == 0
    assert body["curation_scheduled"] is False


