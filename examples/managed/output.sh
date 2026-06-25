#!/usr/bin/env bash
# Print every file the admin must place in a Podclave org bundle, each under a
# "BUNDLE LOCATION:" banner naming its destination path. Placing files in a bundle is a
# manual process (you can't `cp` into it), so: run this, then copy each block into the
# bundle at the path shown. Set KNOW_HOST/KNOW_SECRET in know-identity.sh (the installer's
# onboarding card prints your brain's values).
#   bash examples/managed/output.sh
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

emit() {  # emit <source-file> <bundle-location>
  [ -f "$1" ] || { echo "MISSING: $1" >&2; exit 1; }
  printf '\n# ===== BUNDLE LOCATION: %s =====\n' "$2"
  cat "$1"
}

emit "$HERE/etc/profile.d/know-identity.sh"                  /etc/profile.d/know-identity.sh
emit "$HERE/etc/claude-code/managed-mcp.json"                /etc/claude-code/managed-mcp.json
emit "$HERE/etc/claude-code/managed-settings.d/50-know.json" /etc/claude-code/managed-settings.d/50-know.json
emit "$ROOT/client-plugin/nudge.py"                          /etc/claude-code/know/nudge.py
