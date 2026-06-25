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
