"""Boot self-check + auth probe (spec §9.10, §10.11).

Three DISTINCT checks the installer runs in order and refuses "green" on any
failure — kept distinct so a deprecated model and a bad credential can't mask each
other (spec §10.11):
  1. auth        — an auth-ONLY call (GET /v1/models) that fails only on auth.
  2. version     — `claude` runtime >= floor AND matches the recorded version.
  3. model       — the pinned model id still RESOLVES on the Models list (fails
                   loud when retired -> the known re-pin chore).

Also resolves the cheapest-tier (haiku) dated id at install time. Importable so
/wake reuses auth_probe; runnable as a CLI by install-brain.sh.

Usage:
  python boot_check.py auth                         -> exit 0/1, prints status
  python boot_check.py resolve-model                -> prints the cheapest haiku id
  python boot_check.py model-resolves <id>          -> exit 0/1
  python boot_check.py version <floor>              -> exit 0/1 (+ optional recorded)
  python boot_check.py check <floor> <model> [recorded_ver]   -> full ordered check
"""
import os
import re
import subprocess
import sys

import httpx

API = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def _headers():
    return {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic-version": ANTHROPIC_VERSION}


def auth_probe(timeout: float = 10) -> tuple[bool, str]:
    """Auth-only: a 200 means the credential is good. 401/403 = auth failure
    (distinct, loud); anything else is a transport/quota issue, reported as-is."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY is not set"
    try:
        r = httpx.get(f"{API}/models", headers=_headers(), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"could not reach Anthropic API: {e}"
    if r.status_code == 200:
        return True, "ok"
    if r.status_code in (401, 403):
        return False, f"auth rejected (HTTP {r.status_code}) — key invalid/revoked/over-quota"
    return False, f"unexpected response HTTP {r.status_code}: {r.text[:200]}"


def list_models(timeout: float = 10) -> list[str]:
    r = httpx.get(f"{API}/models?limit=1000", headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def model_resolves(model_id: str, timeout: float = 10) -> bool:
    try:
        r = httpx.get(f"{API}/models/{model_id}", headers=_headers(), timeout=timeout)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def resolve_cheapest_haiku() -> str:
    """Today's concrete dated haiku id (spec §5.2: 'cheapest tier' is human intent;
    resolve it to a concrete id and pin THAT). Prefer the highest dated haiku id;
    fall back to the build-time default if the list is unavailable."""
    try:
        haikus = [m for m in list_models() if "haiku" in m.lower()]
    except Exception:  # noqa: BLE001
        return DEFAULT_HAIKU
    if not haikus:
        return DEFAULT_HAIKU
    # Prefer ids with a trailing date (YYYYMMDD); pick the latest, else any haiku.
    dated = sorted((m for m in haikus if re.search(r"\d{8}$", m)),
                   key=lambda m: re.search(r"(\d{8})$", m).group(1))
    return dated[-1] if dated else sorted(haikus)[-1]


def claude_version() -> str | None:
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def _ver_tuple(v: str):
    return tuple(int(x) for x in v.split("."))


def version_ok(floor: str, recorded: str | None = None) -> tuple[bool, str]:
    cur = claude_version()
    if not cur:
        return False, "could not determine `claude` version"
    if _ver_tuple(cur) < _ver_tuple(floor):
        return False, f"claude {cur} is below the required floor {floor} (run `claude update`)"
    if recorded and cur != recorded:
        return False, f"claude {cur} != the recorded/pinned version {recorded} (un-bisectable drift)"
    return True, cur


def full_check(floor: str, model: str, recorded: str | None = None) -> int:
    ok = True
    a_ok, a_msg = auth_probe()
    print(f"[1/3] auth ............ {'OK' if a_ok else 'FAIL'} — {a_msg}")
    ok &= a_ok
    v_ok, v_msg = version_ok(floor, recorded)
    print(f"[2/3] claude version .. {'OK' if v_ok else 'FAIL'} — {v_msg}")
    ok &= v_ok
    # model-resolves needs auth; only meaningful if auth passed
    m_ok = a_ok and model_resolves(model)
    print(f"[3/3] model resolves .. {'OK' if m_ok else 'FAIL'} — {model}"
          + ("" if m_ok else " (retired/unreachable — re-pin the model line in CLAUDE.md)"))
    ok &= m_ok
    return 0 if ok else 1


def main(argv):
    if not argv:
        print(__doc__); return 2
    cmd = argv[0]
    if cmd == "auth":
        ok, msg = auth_probe(); print(msg); return 0 if ok else 1
    if cmd == "resolve-model":
        print(resolve_cheapest_haiku()); return 0
    if cmd == "model-resolves":
        return 0 if (len(argv) > 1 and model_resolves(argv[1])) else 1
    if cmd == "version":
        ok, msg = version_ok(argv[1], argv[2] if len(argv) > 2 else None)
        print(msg); return 0 if ok else 1
    if cmd == "check":
        if len(argv) < 3:
            print("usage: check <floor> <model> [recorded_version]"); return 2
        return full_check(argv[1], argv[2], argv[3] if len(argv) > 3 else None)
    print(f"unknown command: {cmd}"); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
