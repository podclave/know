#!/usr/bin/env bash
# Validates the org-overlay example templates under examples/managed/:
#   - every *.json parses
#   - the profile.d bridge is valid shell
#   - permissions.allow exactly matches the gateway's tool surface (mcp__know__*)
#   - no second copy of nudge.py is committed (single source = client-plugin/nudge.py)
# No services, no network.  Run:  bash server/test-managed-overlay.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
MGD="$ROOT/examples/managed"
pass=0; fail=0
ok(){ echo "  PASS: $1"; pass=$((pass+1)); }
no(){ echo "  FAIL: $1"; fail=$((fail+1)); }

[ -d "$MGD" ] || { echo "missing $MGD"; exit 1; }

# 1. every committed JSON parses
found_json=0
while IFS= read -r f; do
  found_json=1
  if python3 -m json.tool "$f" >/dev/null 2>&1; then ok "valid JSON: ${f#$ROOT/}"; else no "invalid JSON: ${f#$ROOT/}"; fi
done < <(find "$MGD" -name '*.json')
[ "$found_json" = 1 ] && ok "found overlay JSON templates" || no "no JSON templates under examples/managed"

# 2. profile.d bridge is valid shell
SH="$MGD/etc/profile.d/know-identity.sh"
if [ -f "$SH" ] && bash -n "$SH" 2>/dev/null; then ok "know-identity.sh syntax ok"; else no "know-identity.sh missing or bad syntax"; fi

# 3. no stray nudge.py copy in the overlay (single source is client-plugin/nudge.py)
if find "$MGD" -name 'nudge.py' | grep -q .; then no "stray nudge.py under examples/managed (must reference client-plugin/nudge.py)"; else ok "no stray nudge.py copy"; fi

# 4. permissions.allow <-> gateway tool parity
SETTINGS="$MGD/etc/claude-code/managed-settings.d/50-know.json"
EP="$ROOT/server/gateway/mcp_endpoint.py"
if python3 - "$SETTINGS" "$EP" <<'PY'
import json, re, sys
settings_path, ep_path = sys.argv[1], sys.argv[2]
allow = set(json.load(open(settings_path)).get("permissions", {}).get("allow", []))
names = set(re.findall(r'_t\(\s*"([a-z]+)"', open(ep_path).read()))
expected = {f"mcp__know__{n}" for n in names}
mcp_allow = {a for a in allow if a.startswith("mcp__know__")}
sys.exit(0 if (expected and mcp_allow == expected) else 1)
PY
then ok "permissions.allow matches gateway tools (mcp__know__*)"; else no "permissions.allow drift vs gateway TOOLS"; fi

echo ""; echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
