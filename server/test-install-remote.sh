#!/usr/bin/env bash
# Regression test for install-brain.sh's KB/remote logic (exercised via the
# KB_SETUP_TEST seam) across every path, against a local bare git repo as the remote.
# No services, no network, no API key.  Run:  bash server/test-install-remote.sh
set -u
INSTALL="${1:-$(cd "$(dirname "$0")" && pwd)/install-brain.sh}"
[ -f "$INSTALL" ] || { echo "install script not found: $INSTALL"; exit 1; }
T="$(mktemp -d)"; REMOTE="$T/remote.git"
pass=0; fail=0
ok(){ echo "  PASS: $1"; pass=$((pass+1)); }
no(){ echo "  FAIL: $1"; fail=$((fail+1)); }
git init --bare -q "$REMOTE"

echo "== syntax =="
if bash -n "$INSTALL"; then echo "  syntax ok"; else echo "  SYNTAX ERROR"; exit 1; fi

echo "== fail-fast: no remote and no --no-remote =="
out="$(KB_SETUP_TEST=1 BRAIN_KB_REPO="$T/kbX" bash "$INSTALL" 2>&1)"; rc=$?
[ $rc -ne 0 ] && ok "exits nonzero" || no "should exit nonzero"
echo "$out" | grep -q "No KB remote configured" && ok "prints remote help" || no "missing help text"
[ ! -d "$T/kbX/.git" ] && ok "did NOT create a repo" || no "should not create a repo"

echo "== A: --no-remote (local-only) =="
KB_SETUP_TEST=1 BRAIN_KB_REPO="$T/kbA" bash "$INSTALL" --no-remote >"$T/a.log" 2>&1; rc=$?
[ $rc -eq 0 ] && ok "exits 0" || { no "exit $rc"; cat "$T/a.log"; }
[ -d "$T/kbA/.git" ] && ok "created local repo" || no "no repo"
git -C "$T/kbA" remote | grep -qx mirror && no "should have NO mirror remote" || ok "no mirror remote"
[ -f "$T/kbA/curated/index.md" ] && ok "seeded curated/index.md" || no "no index.md"

echo "== B: fresh (empty) remote -> seed + push =="
KB_SETUP_TEST=1 BRAIN_KB_REPO="$T/kbB" BRAIN_REMOTE_URL="$REMOTE" bash "$INSTALL" >"$T/b.log" 2>&1; rc=$?
[ $rc -eq 0 ] && ok "exits 0" || { no "exit $rc"; cat "$T/b.log"; }
git -C "$T/kbB" remote get-url mirror 2>/dev/null | grep -q "remote.git" && ok "wired mirror remote" || no "no mirror remote"
[ -n "$(git ls-remote "$REMOTE" 2>/dev/null)" ] && ok "pushed: remote now has commits" || no "remote still empty"

# seed a distinctive fact into the remote (via B) so restore is observable
printf -- '---\ntype: Fact\ntitle: Restore Canary\n---\nthis fact must survive a restore.\n' > "$T/kbB/curated/restore-canary.md"
git -C "$T/kbB" add -A
git -C "$T/kbB" -c user.name=t -c user.email=t@t commit -q -m "add restore canary"
git -C "$T/kbB" push -q mirror HEAD
B_COUNT="$(git -C "$T/kbB" rev-list --count HEAD)"

echo "== C: existing (non-empty) remote -> RESTORE onto a fresh box =="
KB_SETUP_TEST=1 BRAIN_KB_REPO="$T/kbC" BRAIN_REMOTE_URL="$REMOTE" bash "$INSTALL" >"$T/c.log" 2>&1; rc=$?
[ $rc -eq 0 ] && ok "exits 0" || { no "exit $rc"; cat "$T/c.log"; }
[ -f "$T/kbC/curated/restore-canary.md" ] && ok "RESTORED the canary fact" || no "canary missing after restore"
[ "$(git -C "$T/kbC" rev-list --count HEAD 2>/dev/null)" = "$B_COUNT" ] && ok "history matches B ($B_COUNT commits)" || no "history mismatch"
grep -qi "restoring KB from remote" "$T/c.log" && ok "took the restore path (not seed)" || no "did not log restore"

echo "== re-run on existing KB (reuse) =="
KB_SETUP_TEST=1 BRAIN_KB_REPO="$T/kbB" BRAIN_REMOTE_URL="$REMOTE" bash "$INSTALL" >"$T/r.log" 2>&1; rc=$?
[ $rc -eq 0 ] && ok "re-run exits 0" || { no "exit $rc"; cat "$T/r.log"; }
grep -qi "reusing" "$T/r.log" && ok "reused existing KB" || no "did not reuse"

echo ""; echo "RESULT: $pass passed, $fail failed"
rm -rf "$T"
[ $fail -eq 0 ]
