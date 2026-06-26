"""App endpoint tests — healthz inventory (no agent, no network)."""
import asyncio
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


def test_viewer_url_uses_configured_public_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://brain.example.com")
    monkeypatch.setattr(config, "SECRET", "sekret")
    out = asyncio.run(know_app.Handlers(tmp_path).viewer("https://ignored.host"))
    assert "https://brain.example.com/viewer/sekret/" in out


def test_viewer_url_falls_back_to_dialed_host(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    monkeypatch.setattr(config, "SECRET", "sk2")
    out = asyncio.run(know_app.Handlers(tmp_path).viewer("https://dialed.host/"))
    assert "https://dialed.host/viewer/sk2/" in out


def test_viewer_url_unconfigured_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    monkeypatch.setattr(config, "SECRET", "sk3")
    out = asyncio.run(know_app.Handlers(tmp_path).viewer(""))
    assert "isn't configured" in out
    assert "sk3" not in out  # don't leak the secret in a URL we can't actually build


