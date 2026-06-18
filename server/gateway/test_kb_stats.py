"""KB inventory helpers."""
from kb_stats import fact_counts, kb_snapshot, secretary_behind


def test_fact_counts_excludes_index(tmp_path):
    cur = tmp_path / "curated"
    raw = tmp_path / "raw"
    cur.mkdir()
    raw.mkdir()
    (cur / "index.md").write_text("index\n")
    (cur / "fact.md").write_text("fact\n")
    (raw / "r.md").write_text("raw\n")
    assert fact_counts(tmp_path) == (1, 1)


def test_secretary_behind_heuristic():
    assert secretary_behind(1, 0) is False
    assert secretary_behind(1, 8) is True
    assert secretary_behind(0, 3) is True


def test_kb_snapshot_open_contradictions(tmp_path):
    contra = tmp_path / "contradictions"
    contra.mkdir()
    (contra / "dispute.md").write_text("open\n")
    resolved = contra / "resolved"
    resolved.mkdir()
    (resolved / "old.md").write_text("closed\n")
    snap = kb_snapshot(tmp_path)
    assert snap["open_contradictions"] == 1
