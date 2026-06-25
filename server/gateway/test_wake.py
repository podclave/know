"""wake.py CLI — mirror-pull + reconcile + liveness, against a fake repo. No agent."""
from unittest.mock import patch

import pytest

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


@pytest.mark.parametrize("benign_status", ["skipped", "deferred"])
def test_wake_benign_statuses_do_not_alert(tmp_path, benign_status):
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
         patch("wake.run_pass", return_value={"status": benign_status}), \
         patch("wake._alert") as alert:
        out = wake.wake(tmp_path)
    assert out["reconcile"] == benign_status
    alert.assert_not_called()
