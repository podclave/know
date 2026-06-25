"""Boot self-check — credential-free SDK runtime checks.

`know` makes no claims about auth: it runs the Claude Agent SDK and expects `claude` to
already work on the box (whatever credential the operator has — subscription token, API
key, logged-in ~/.claude). So there is NO auth probe and NO REST model-resolution here;
the install-time save+recall smoke test is the real auth+model check, and it WARNS
rather than blocks. What remains needs no credential:
  • runtime — the SDK's bundled CLI >= floor AND matches the recorded version.

Usage:
  python boot_check.py sdk-version            -> prints the bundled CLI version
  python boot_check.py version <floor>        -> exit 0/1 (+ optional recorded)
  python boot_check.py check <floor> [recorded_ver]   -> runtime check
"""
import sys


def sdk_cli_version() -> str | None:
    """The Claude Code CLI version BUNDLED with the installed Agent SDK — the agent
    runtime recall/the secretary actually run on. Pinned by the SDK, native + Node-free,
    isolated from any system `claude`."""
    try:
        from claude_agent_sdk._cli_version import __cli_version__
        return __cli_version__
    except Exception:  # noqa: BLE001
        return None


def _ver_tuple(v: str):
    return tuple(int(x) for x in v.split("."))


def version_ok(floor: str, recorded: str | None = None) -> tuple[bool, str]:
    cur = sdk_cli_version()
    if not cur:
        return False, "could not determine the SDK's bundled CLI version (is claude-agent-sdk installed?)"
    if _ver_tuple(cur) < _ver_tuple(floor):
        return False, f"bundled CLI {cur} is below the required floor {floor} (bump claude-agent-sdk)"
    if recorded and cur != recorded:
        return False, f"bundled CLI {cur} != the recorded/pinned version {recorded} (bump the SDK pin + re-record)"
    return True, cur


def full_check(floor: str, recorded: str | None = None) -> int:
    v_ok, v_msg = version_ok(floor, recorded)
    print(f"[1/1] agent runtime ... {'OK' if v_ok else 'FAIL'} — bundled CLI {v_msg}")
    return 0 if v_ok else 1


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "sdk-version":
        v = sdk_cli_version()
        print(v or "")
        return 0 if v else 1
    if cmd == "version":
        ok, msg = version_ok(argv[1], argv[2] if len(argv) > 2 else None)
        print(msg)
        return 0 if ok else 1
    if cmd == "check":
        if len(argv) < 2:
            print("usage: check <floor> [recorded_version]")
            return 2
        return full_check(argv[1], argv[2] if len(argv) > 2 else None)
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
