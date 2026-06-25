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

# 2. profile.d bridge is valid shell and sets all three env vars in one place
SH="$MGD/etc/profile.d/know-identity.sh"
if [ -f "$SH" ] && bash -n "$SH" 2>/dev/null; then ok "know-identity.sh syntax ok"; else no "know-identity.sh missing or bad syntax"; fi
for v in KNOW_HOST KNOW_SECRET KNOW_USER; do
  grep -qE "^export $v=" "$SH" 2>/dev/null && ok "know-identity.sh exports $v" || no "know-identity.sh does not export $v"
done

# 2b. the connector URL is env-driven (no <placeholders> left to hand-edit per deploy)
MCP="$MGD/etc/claude-code/managed-mcp.json"
for tok in '${KNOW_HOST}' '${KNOW_SECRET}' '${KNOW_USER'; do
  grep -qF "$tok" "$MCP" 2>/dev/null && ok "managed-mcp.json references $tok" || no "managed-mcp.json missing $tok"
done
if grep -qE '<[a-z-]+>' "$MCP" 2>/dev/null; then no "managed-mcp.json still has a <placeholder> (should be env-driven)"; else ok "managed-mcp.json has no <placeholders>"; fi

# 3. no stray nudge.py copy in the overlay (single source is client-plugin/nudge.py)
if find "$MGD" -name 'nudge.py' | grep -q .; then no "stray nudge.py under examples/managed (must reference client-plugin/nudge.py)"; else ok "no stray nudge.py copy"; fi

# 4. permissions.allow <-> gateway tool parity
SETTINGS="$MGD/etc/claude-code/managed-settings.d/50-know.json"
EP="$ROOT/server/gateway/mcp_endpoint.py"
if python3 - "$SETTINGS" "$EP" <<'PY'
import json, re, sys
settings_path, ep_path = sys.argv[1], sys.argv[2]
allow = set(json.load(open(settings_path)).get("permissions", {}).get("allow", []))
names = set(re.findall(r'_t\(\s*"([a-z_]+)"', open(ep_path).read()))
expected = {f"mcp__know__{n}" for n in names}
mcp_allow = {a for a in allow if a.startswith("mcp__know__")}
sys.exit(0 if (expected and mcp_allow == expected) else 1)
PY
then ok "permissions.allow matches gateway tools (mcp__know__*)"; else no "permissions.allow drift vs gateway TOOLS"; fi

# 5. output.sh is the single source of placement: it runs and emits every bundle file
#    under its "BUNDLE LOCATION:" banner, with the file's real content.
OUT="$MGD/output.sh"
if [ -f "$OUT" ] && bash -n "$OUT" 2>/dev/null; then ok "output.sh syntax ok"; else no "output.sh missing or bad syntax"; fi
rendered="$(bash "$OUT" 2>/dev/null || true)"
for loc in \
  "/etc/profile.d/know-identity.sh" \
  "/etc/claude-code/managed-mcp.json" \
  "/etc/claude-code/managed-settings.d/50-know.json" \
  "/etc/claude-code/know/nudge.py"; do
  echo "$rendered" | grep -qF "BUNDLE LOCATION: $loc" && ok "output.sh banners $loc" || no "output.sh missing banner for $loc"
done
echo "$rendered" | grep -q 'mcpServers'        && ok "output.sh cats managed-mcp.json"   || no "output.sh missing managed-mcp content"
echo "$rendered" | grep -q 'mcp__know__recall' && ok "output.sh cats 50-know.json"        || no "output.sh missing settings content"
echo "$rendered" | grep -q 'KNOW_HOST'         && ok "output.sh cats know-identity.sh"    || no "output.sh missing identity content"
echo "$rendered" | grep -qF '<know-nudge>'     && ok "output.sh cats nudge.py"            || no "output.sh missing nudge content"

# 6. output.sh fills in KNOW_HOST/KNOW_SECRET when passed (no hand-edit needed)
filled="$(KNOW_HOST=h.example.test KNOW_SECRET=deadbeefcafe bash "$OUT" 2>/dev/null || true)"
echo "$filled" | grep -q 'KNOW_HOST="h.example.test"'   && ok "output.sh fills KNOW_HOST"   || no "output.sh did not fill KNOW_HOST"
echo "$filled" | grep -q 'KNOW_SECRET="deadbeefcafe"'   && ok "output.sh fills KNOW_SECRET" || no "output.sh did not fill KNOW_SECRET"
echo "$filled" | grep -qF '<brain-host>'                && no "output.sh left a <brain-host> placeholder when values were passed" || ok "no placeholder left when values passed"

echo ""; echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
