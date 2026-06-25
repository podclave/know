#!/usr/bin/env bash
# Print every file the admin must place in a Podclave org bundle, each under a
# "BUNDLE LOCATION:" banner naming its destination path. Placing files in a bundle is a
# manual process (you can't `cp` into it), so: run this, then paste each block into the
# bundle at the path shown.
#
# Run it on the brain box (the same place you ran the installer) and it auto-fills
# know-identity.sh: the secret is read from ~/.know/secret and the host from `sprite-env
# info` — exactly where the installer put them. To generate the blocks somewhere else,
# override with env vars: KNOW_HOST=your-brain.example.com KNOW_SECRET=<secret> bash output.sh
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

# Discover this brain's host + secret the way the installer stored them (env overrides win).
: "${KNOW_SECRET:=}"
if [ -z "$KNOW_SECRET" ] && [ -f "$HOME/.know/secret" ]; then
  KNOW_SECRET="$(cat "$HOME/.know/secret")"
fi
: "${KNOW_HOST:=}"
if [ -z "$KNOW_HOST" ]; then
  _url="$(sprite-env info 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sprite_url",""))' 2>/dev/null || true)"
  KNOW_HOST="${_url#*://}"; KNOW_HOST="${KNOW_HOST%/}"
fi

banner() { printf '\n# ===== BUNDLE LOCATION: %s =====\n' "$1"; }
exists() { [ -f "$1" ] || { echo "MISSING: $1" >&2; exit 1; }; }

ID="$HERE/etc/profile.d/know-identity.sh"
exists "$ID"
banner /etc/profile.d/know-identity.sh
if [ -n "$KNOW_HOST" ] && [ -n "$KNOW_SECRET" ]; then
  # hex secret + hostname are sed-safe with a '|' delimiter
  sed -e "s|<brain-host>|${KNOW_HOST}|" -e "s|<shared-secret>|${KNOW_SECRET}|" "$ID"
else
  cat "$ID"
  printf '# (run on the brain box to auto-fill, or pass KNOW_HOST=... KNOW_SECRET=...)\n'
fi

emit() { exists "$1"; banner "$2"; cat "$1"; }
emit "$HERE/etc/claude-code/managed-mcp.json"                /etc/claude-code/managed-mcp.json
emit "$HERE/etc/claude-code/managed-settings.d/50-know.json" /etc/claude-code/managed-settings.d/50-know.json
emit "$ROOT/client-plugin/nudge.py"                          /etc/claude-code/know/nudge.py
