#!/usr/bin/env bash
# Print every file the admin must place in a Podclave org bundle, each under a
# "BUNDLE LOCATION:" banner naming its destination path. Placing files in a bundle is a
# manual process (you can't `cp` into it), so: run this, then paste each block into the
# bundle at the path shown.
#
# Pass your brain's values to fill know-identity.sh automatically (the installer's
# onboarding card prints a ready-to-paste command):
#   KNOW_HOST=your-brain.example.com KNOW_SECRET=<secret> bash examples/managed/output.sh
# Without them, know-identity.sh prints with <brain-host>/<shared-secret> to edit by hand.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

banner() { printf '\n# ===== BUNDLE LOCATION: %s =====\n' "$1"; }
exists() { [ -f "$1" ] || { echo "MISSING: $1" >&2; exit 1; }; }

ID="$HERE/etc/profile.d/know-identity.sh"
exists "$ID"
banner /etc/profile.d/know-identity.sh
if [ -n "${KNOW_HOST:-}" ] && [ -n "${KNOW_SECRET:-}" ]; then
  # hex secret + hostname are sed-safe with a '|' delimiter
  sed -e "s|<brain-host>|${KNOW_HOST}|" -e "s|<shared-secret>|${KNOW_SECRET}|" "$ID"
else
  cat "$ID"
  printf '# (re-run with KNOW_HOST=... KNOW_SECRET=... to fill these in automatically)\n'
fi

emit() { exists "$1"; banner "$2"; cat "$1"; }
emit "$HERE/etc/claude-code/managed-mcp.json"                /etc/claude-code/managed-mcp.json
emit "$HERE/etc/claude-code/managed-settings.d/50-know.json" /etc/claude-code/managed-settings.d/50-know.json
emit "$ROOT/client-plugin/nudge.py"                          /etc/claude-code/know/nudge.py
