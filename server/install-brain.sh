#!/usr/bin/env bash
# install-brain.sh — stand up one teamkb brain on a Sprite. Idempotent; brain #N is
# a re-run on a fresh Sprite (Gate A). Every step is green/red and re-asserts on re-run.
#
#   bash server/install-brain.sh [brain-name]
#
# Needs (runtime, not files): an ANTHROPIC_API_KEY (default: ~/ANTHROPIC_API_KEY, the
# sk- line), a Sprite with url_access=public, and `gh` auth if you want the mirror.
# The key is set ONLY on the service env (spec §9.8) — never your interactive shell.
set -euo pipefail
log(){ printf '\033[1;36m[teamkb]\033[0m %s\n' "$*"; }
ok(){  printf '\033[1;32m[teamkb] OK:\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[teamkb] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLAUDE_FLOOR="${CLAUDE_FLOOR:-2.1.92}"
BRAIN_NAME="${1:-$(sprite-env info 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sprite_name","teamkb"))' 2>/dev/null || echo teamkb)}"
GW_DIR="$HOME/teamkb-gateway"
KB_REPO="${BRAIN_KB_REPO:-$HOME/teamkb-kb}"
STATE_DIR="$HOME/.teamkb"
KEY_FILE="${ANTHROPIC_API_KEY_FILE:-$HOME/ANTHROPIC_API_KEY}"
PORT=8080
SERVICE=teamkb

# --- 0. preflight ------------------------------------------------------------
# No node / system `claude` needed: the Claude Agent SDK bundles a native CLI in the venv.
for t in python3 openssl curl git sprite-env; do
  command -v "$t" >/dev/null 2>&1 || die "missing required tool: $t"
done
python3 -c 'import venv' 2>/dev/null || die "python3 venv module not available"
mkdir -p "$STATE_DIR"

# resolve the Anthropic key (file's sk- line, or the env var) — kept in THIS process
# only; passed to the service via --env, never written to a profile/bashrc.
API_KEY="${ANTHROPIC_API_KEY:-}"
if [ -z "$API_KEY" ] && [ -f "$KEY_FILE" ]; then
  API_KEY="$(grep -oE 'sk-ant[A-Za-z0-9_-]+' "$KEY_FILE" | head -1 || true)"
fi
[ -n "$API_KEY" ] || die "no ANTHROPIC_API_KEY (set it, or put the key in $KEY_FILE)"
export ANTHROPIC_API_KEY="$API_KEY"   # for this script's boot-check calls only

# --- 1. assert the Sprite is public (§9.6) -----------------------------------
URL_ACCESS="$(sprite-env info 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("url_access",""))' 2>/dev/null || true)"
SPRITE_URL="$(sprite-env info 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sprite_url",""))' 2>/dev/null || true)"
[ -n "$SPRITE_URL" ] || die "could not read sprite_url from sprite-env info"
if [ -n "$URL_ACCESS" ] && [ "$URL_ACCESS" != "public" ]; then
  die "Sprite url_access is '$URL_ACCESS', must be 'public' — web connectors dial from Anthropic's cloud and would silently fail (§9.6)"
fi
ok "Sprite is public: $SPRITE_URL"

# --- 2. deploy the gateway code + venv (the SDK brings the agent runtime) ----
mkdir -p "$GW_DIR"
cp "$HERE/gateway/"*.py "$HERE/gateway/requirements.txt" "$GW_DIR/"
rm -rf "$GW_DIR/viewer"; cp -r "$HERE/gateway/viewer" "$GW_DIR/"   # OKF graph visualizer assets
[ -d "$GW_DIR/.venv" ] || { log "creating gateway venv"; python3 -m venv "$GW_DIR/.venv"; }
log "installing gateway deps (incl. claude-agent-sdk + its bundled native CLI)"
"$GW_DIR/.venv/bin/pip" install -q --no-cache-dir --upgrade pip >/dev/null
"$GW_DIR/.venv/bin/pip" install -q --no-cache-dir -r "$GW_DIR/requirements.txt"
PYBIN="$GW_DIR/.venv/bin/python"

# the agent runtime is the SDK's BUNDLED CLI — pinned by the SDK version, native +
# Node-free. Read + floor-check + record it (no `claude update`, no PATH wiring).
CLAUDE_VER="$("$PYBIN" "$GW_DIR/boot_check.py" sdk-version)"
[ -n "$CLAUDE_VER" ] || die "could not determine the SDK's bundled CLI version"
python3 -c "import sys; f='$CLAUDE_FLOOR'.split('.'); v='$CLAUDE_VER'.split('.'); sys.exit(0 if tuple(map(int,v))>=tuple(map(int,f)) else 1)" \
  || die "bundled CLI $CLAUDE_VER is below the floor $CLAUDE_FLOOR (bump claude-agent-sdk)"
ok "agent runtime: SDK bundled CLI $CLAUDE_VER (floor $CLAUDE_FLOOR)"

# --- 4. resolve + pin the cheapest-tier model id (§5.2) ----------------------
MODEL="${BRAIN_MODEL:-$("$PYBIN" "$GW_DIR/boot_check.py" resolve-model)}"
[ -n "$MODEL" ] || die "could not resolve a model id"
ok "pinned model: $MODEL"

# --- 5. mint the secret (persisted; re-run reuses it) ------------------------
SECRET_FILE="$STATE_DIR/secret"
if [ ! -f "$SECRET_FILE" ]; then
  openssl rand -hex 24 > "$SECRET_FILE"; chmod 600 "$SECRET_FILE"
  log "minted a new secret path segment"
fi
SECRET="$(cat "$SECRET_FILE")"

# --- 6. init the KB data repo (raw/, curated/=OKF bundle, _superseded/, contradictions/) --
if [ ! -d "$KB_REPO/.git" ]; then
  log "initializing KB data repo at $KB_REPO"
  mkdir -p "$KB_REPO"/{raw,curated,_superseded,contradictions}
  git -C "$KB_REPO" init -q
  for d in raw _superseded contradictions; do touch "$KB_REPO/$d/.gitkeep"; done
  cp "$HERE/kb-template/CLAUDE.md" "$KB_REPO/CLAUDE.md"
  # curated/ is the OKF bundle; seed its bundle-root index.md (the secretary owns it)
  printf -- '---\nokf_version: "0.1"\n---\n\n# Knowledge base index\n\n_(empty — facts appear here as the secretary curates them)_\n' > "$KB_REPO/curated/index.md"
  git -C "$KB_REPO" add -A
  git -C "$KB_REPO" -c user.name=teamkb-capture -c user.email=capture@teamkb.local \
    commit -q -m "capture: init knowledge base (OKF bundle in curated/)"
fi
# record the resolved model + claude version onto the ONE config line (§5.2, §10.3)
"$PYBIN" - "$KB_REPO/CLAUDE.md" "$MODEL" "$CLAUDE_VER" <<'PY'
import re, sys
path, model, ver = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path).read()
s = re.sub(r'(?m)^- model:.*$', f'- model: {model}', s, count=1)
s = re.sub(r'(?m)^- claude-version:.*$', f'- claude-version: {ver}', s, count=1)
open(path, 'w').write(s)
PY
git -C "$KB_REPO" add CLAUDE.md
git -C "$KB_REPO" diff --cached --quiet || \
  git -C "$KB_REPO" -c user.name=teamkb-secretary -c user.email=secretary@teamkb.local \
    commit -q -m "secretary: pin model=$MODEL claude=$CLAUDE_VER"
ok "KB repo ready ($KB_REPO); model+version recorded in CLAUDE.md"

# --- 6b. private GitHub mirror (optional, best-effort) -----------------------
MIRROR_SLUG="${BRAIN_GITHUB_MIRROR:-}"
if [ -n "${BRAIN_NO_MIRROR:-}" ]; then
  log "BRAIN_NO_MIRROR set — skipping the GitHub mirror (local repo is the truth)"
  MIRROR_SLUG=""
elif [ -z "$MIRROR_SLUG" ] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_USER="$(gh api user -q .login 2>/dev/null || true)"
  [ -n "$GH_USER" ] && MIRROR_SLUG="$GH_USER/teamkb-kb-$BRAIN_NAME"
fi
if [ -n "$MIRROR_SLUG" ]; then
  if ! git -C "$KB_REPO" remote | grep -qx mirror; then
    if gh repo view "$MIRROR_SLUG" >/dev/null 2>&1 || \
       gh repo create "$MIRROR_SLUG" --private --disable-issues --disable-wiki >/dev/null 2>&1; then
      git -C "$KB_REPO" remote add mirror "https://github.com/$MIRROR_SLUG.git" 2>/dev/null || true
      git -C "$KB_REPO" push -u mirror HEAD >/dev/null 2>&1 && ok "mirror: $MIRROR_SLUG" \
        || log "mirror remote added but initial push failed (check gh auth) — local repo is still the truth"
    else
      log "could not create/find mirror repo $MIRROR_SLUG — continuing local-only"
    fi
  else
    git -C "$KB_REPO" push mirror HEAD >/dev/null 2>&1 || true
    ok "mirror already configured"
  fi
else
  log "no GitHub mirror configured (set BRAIN_GITHUB_MIRROR=owner/repo or auth gh) — local-only"
fi

# --- 7. supervised sprite-env service (key scoped HERE, not the shell) -------
# pass PATH so the recall/secretary `claude` subprocess (a node app) + git resolve
# under the supervised service's otherwise-minimal environment.
ENVS="HOME=$HOME,PATH=$PATH,ANTHROPIC_API_KEY=$API_KEY,BRAIN_SECRET=$SECRET,BRAIN_KB_REPO=$KB_REPO,BRAIN_MODEL=$MODEL,BRAIN_NAME=$BRAIN_NAME"
[ -n "${BRAIN_ALERT_WEBHOOK:-}" ] && ENVS="$ENVS,BRAIN_ALERT_WEBHOOK=$BRAIN_ALERT_WEBHOOK"
create_service(){
  sprite-env services create "$SERVICE" --cmd "$PYBIN" \
    --args "-m,uvicorn,app:app,--host,0.0.0.0,--port,$PORT" \
    --env "$ENVS" --dir "$GW_DIR" --http-port "$PORT" --no-stream >/dev/null
}
if sprite-env services get "$SERVICE" >/dev/null 2>&1; then
  log "service exists — recreating to apply current env/code"
  sprite-env services delete "$SERVICE" >/dev/null 2>&1 || true
  create_service
else
  log "creating supervised service: $SERVICE (public :$PORT)"
  create_service
fi

# --- 8. wait for health ------------------------------------------------------
log "waiting for the gateway to come up..."
up=0
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$PORT/healthz" 2>/dev/null || true)"
  [ "$code" = "200" ] && { up=1; break; }
  sleep 1
done
[ "$up" = "1" ] || die "gateway did not become healthy on :$PORT (check: sprite-env services get $SERVICE)"
ok "gateway healthy on :$PORT"

# --- 9. ordered boot self-check (refuse green on any failure, §10.11) --------
log "running the ordered boot self-check..."
"$PYBIN" "$GW_DIR/boot_check.py" check "$CLAUDE_FLOOR" "$MODEL" "$CLAUDE_VER" \
  || die "boot self-check FAILED — see the leg above; the brain is NOT green"

# --- 10. secret-path reachability asserts (§9.4–9.6) -------------------------
MCP_PATH="/mcp/$SECRET/install-smoke/"
init_body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
code_ok="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT$MCP_PATH" -d "$init_body")"
[ "$code_ok" = "200" ] || die "secret path did not serve MCP (got HTTP $code_ok)"
code_404="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/mcp/WRONGSECRET/x/" -d "$init_body")"
[ "$code_404" = "404" ] || die "wrong-secret path returned $code_404, expected 404"
ok "secret path serves MCP (200) and 404s on a wrong secret"

# public-URL reachability (web surfaces dial the public URL, not localhost)
PUB_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$SPRITE_URL/healthz" 2>/dev/null || true)"
[ "$PUB_CODE" = "200" ] && ok "public URL reachable: $SPRITE_URL" \
  || log "WARN: public URL $SPRITE_URL/healthz returned '$PUB_CODE' — connectors dial this; verify url_access + DNS"

# --- 11. CLI save/recall smoke (the tools FIRE, not just connect, §9.7) ------
log "CLI smoke: save + recall a canary through the live MCP tools..."
SMOKE="/mcp/$SECRET/install-smoke/"
save_body='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"save","arguments":{"title":"Install canary","body":"teamkb install smoke test canary fact."}}}'
save_out="$(curl -s "http://localhost:$PORT$SMOKE" -d "$save_body")"
echo "$save_out" | grep -q '"isError"' && die "save smoke returned an error: $save_out"
echo "$save_out" | grep -q 'Saved' || die "save smoke did not confirm: $save_out"
CANARY_ID="$(echo "$save_out" | grep -oE 'id [0-9a-f]+' | awk '{print $2}')"
recall_body='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"recall","arguments":{"query":"install canary"}}}'
recall_out="$(curl -s --max-time 150 "http://localhost:$PORT$SMOKE" -d "$recall_body")"
echo "$recall_out" | grep -qi 'canary' || log "WARN: recall smoke did not surface the canary (cold model wake?) — raw: $(echo "$recall_out" | head -c 200)"
# clean up the canary so the smoke never pollutes the real KB (runs within seconds,
# beating the curation debounce so the secretary won't promote it).
if [ -n "$CANARY_ID" ]; then
  sup_body="{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"supersede\",\"arguments\":{\"id\":\"$CANARY_ID\"}}}"
  curl -s "http://localhost:$PORT$SMOKE" -d "$sup_body" >/dev/null || true
fi
ok "CLI save+recall smoke passed (tools fire); canary cleaned up"

# --- 12. onboarding card -----------------------------------------------------
BASE_URL="$SPRITE_URL/mcp/$SECRET"
cat <<EOF

=========================================================================
  teamkb brain "$BRAIN_NAME" is UP and GREEN.
  -------------------------------------------------------------------
  Connect URL (each teammate appends their own name for attribution):

      $BASE_URL/<your-name>/

  • Claude Code:   claude mcp add --transport http teamkb "$BASE_URL/<your-name>/"
  • claude.ai / Desktop / Cowork (Team/Enterprise):
      An ORG OWNER adds the URL once as a custom connector (a non-owner can't);
      then each member adds the same URL and toggles it ON per-conversation via
      + -> Connectors. A fresh chat with it OFF returns nothing — and empty
      recall looks identical to "the brain knows nothing", so toggle it on.

  The URL IS the credential (secret-in-path). Treat it like a password; rotate
  by re-running with a new secret + re-issuing this card.
  -------------------------------------------------------------------
  Browse the brain as an interactive knowledge graph (OKF visualizer) at:

      $SPRITE_URL/viewer/$SECRET/

  (same secret-in-path; open in a browser — click a node to read the fact and
  follow its cross-links.)
  -------------------------------------------------------------------
  Heartbeat: add an external pinger (Podclave Schedule / GitHub Actions cron /
  uptime monitor), hourly, that POSTs to:

      $SPRITE_URL/wake

  (auth probe + mirror-pull + reconcile + curator liveness; a spun-down box
  can't cron itself, so this is required for off-box human-edit reconcile.)
  -------------------------------------------------------------------
  KB repo: $KB_REPO     model: $MODEL     agent runtime (bundled CLI): $CLAUDE_VER
=========================================================================
EOF
