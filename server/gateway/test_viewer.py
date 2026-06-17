"""Viewer tests — the OKF graph generator (teamkb-authored logic) and the
secret-gated /viewer route. No network: cytoscape/marked are CDN <script> tags in
the emitted HTML, never fetched here."""
import json

import pytest
from fastapi.testclient import TestClient

from store import GitStore
from viewer.generator import generate_html


def _bundle(tmp_path):
    """A tiny curated OKF bundle: two concepts, one cross-link."""
    s = GitStore(tmp_path / "kb")
    s.ensure_layout()
    cur = s.repo / "curated"
    (cur / "gateway.md").write_text(
        "---\ntype: Architecture\ntitle: Gateway\ndescription: Kong gw\ntags: [net]\n---\n"
        "Fronts the [database](database.md).\n")
    (cur / "database.md").write_text(
        "---\ntype: Decision\ntitle: Database\ndescription: postgres\n---\nPostgres 16.\n")
    (cur / "index.md").write_text('---\nokf_version: "0.1"\n---\n# index\n')
    return s.repo


def test_generate_html_embeds_graph(tmp_path):
    html = generate_html(_bundle(tmp_path) / "curated", bundle_name="mybrain")
    # template fully substituted (no placeholders left)
    for placeholder in ("__BUNDLE_DATA__", "__BUNDLE_NAME__", "/*__VIZ_CSS__*/", "/*__VIZ_JS__*/"):
        assert placeholder not in html
    assert "mybrain" in html and "cytoscape" in html
    # the embedded graph has both concepts as nodes and the gateway->database edge
    blob = html.split("window.BUNDLE = ", 1)[1].split("</script>", 1)[0].strip().rstrip(";")
    graph = json.loads(blob)
    ids = {n["data"]["id"] for n in graph["nodes"]}
    assert ids == {"gateway", "database"}          # index.md excluded
    assert {"Architecture", "Decision"} <= set(graph["types"])
    assert any(e["data"]["source"] == "gateway" and e["data"]["target"] == "database"
               for e in graph["edges"])


def test_generate_html_empty_bundle_is_valid(tmp_path):
    s = GitStore(tmp_path / "kb"); s.ensure_layout()
    html = generate_html(s.repo / "curated", bundle_name="empty")
    assert "<html" in html and "__BUNDLE_DATA__" not in html


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app.config, "SECRET", "vsecret")
    monkeypatch.setattr(app, "KB_REPO", _bundle(tmp_path))
    return TestClient(app.app)


def test_viewer_wrong_secret_is_404(client):
    assert client.get("/viewer/nope/").status_code == 404


def test_viewer_right_secret_renders_html(client):
    r = client.get("/viewer/vsecret/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "cytoscape" in r.text and "Gateway" in r.text