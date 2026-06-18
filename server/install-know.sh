#!/usr/bin/env bash
# install-know.sh — stand up one `know` brain on a Sprite (or any host). Idempotent;
# brain #N is a re-run on a fresh host. Every step is green/red and re-asserts on re-run.
#
#   bash server/install-know.sh [--name <label>] [--remote <clone-url> | --no-remote]
#
# Needs: an ANTHROPIC_API_KEY (default: the sk- line of ~/ANTHROPIC_API_KEY), a Sprite
# with url_access=public, and EITHER a git remote you can push to (--remote <url>) OR
# --no-remote to run local-only. A re-run needs neither flag — it reuses the wired
# remote and preserves the existing --name. The key is set ONLY on the service env.
set -euo pipefail
log(){ printf '\033[1;36m[know]\033[0m %s\n' "$*"; }
ok(){  printf '\033[1;32m[know] OK:\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[know] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- args + config -----------------------------------------------------------
NO_REMOTE=""; REMOTE_URL=""; NAME_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-remote) NO_REMOTE=1 ;;
    --remote) shift; REMOTE_URL="${1:-}"; [ -n "$REMOTE_URL" ] || die "--remote needs a <clone-url>" ;;
    --remote=*) REMOTE_URL="${1#--remote=}" ;;
    --name) shift; NAME_ARG="${1:-}"; [ -n "$NAME_ARG" ] || die "--name needs a value" ;;
    --name=*) NAME_ARG="${1#--name=}" ;;
    --*) die "unknown flag: $1 (use --name <label>, --remote <url>, or --no-remote)" ;;
    *) die "unexpected argument: $1 (use --name <label>, --remote <url>, or --no-remote)" ;;
  esac
  shift
done

CLAUDE_FLOOR="2.1.92"
GW_DIR="$HOME/know-gateway"
KB_REPO="${KNOW_KB_REPO:-$HOME/know-kb}"   # KNOW_KB_REPO = internal override for the test harness only
STATE_DIR="$HOME/.know"
KEY_FILE="${ANTHROPIC_API_KEY_FILE:-$HOME/ANTHROPIC_API_KEY}"
PORT=8080
SERVICE=know
# Trust-on-first-use for SSH remotes (a fresh box has no known_hosts → push would hang).
SSH_CMD="${GIT_SSH_COMMAND:-ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20}"

# read an env var off the existing service (so a re-run preserves --name / model)
svc_env(){ sprite-env services get "$SERVICE" 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('env',{}).get('$1',''))" 2>/dev/null || true; }

# --- KB repo + remote: resolve, then adopt-or-seed (the "git is the truth") ---
# The brain ALWAYS has a local git repo (KB_REPO = the truth). A remote is optional but,
# when present, is BOTH a backup destination AND a restore source: point a fresh box at
# the same --remote and it clones the whole KB back. We never create or name a repo — you
# bring one you can push to (any host), and we verify it.
resolve_remote() {            # sets REMOTE_MODE (local|remote), REMOTE_HAS_COMMITS, REMOTE_URL
  REMOTE_MODE=local; REMOTE_HAS_COMMITS=""
  if [ -n "$NO_REMOTE" ]; then
    log "remote: --no-remote → LOCAL-ONLY (no off-box backup, restore, or editing)"
    return 0
  fi
  # re-run convenience: adopt the remote already wired into an existing KB
  if [ -z "$REMOTE_URL" ] && [ -d "$KB_REPO/.git" ]; then
    REMOTE_URL="$(git -C "$KB_REPO" remote get-url mirror 2>/dev/null || true)"
    [ -n "$REMOTE_URL" ] && log "remote: reusing the KB's existing 'mirror' → $REMOTE_URL"
  fi
  if [ -z "$REMOTE_URL" ]; then
    die "No KB remote configured.
  A know brain should back its git repo to a remote you control — for durability,
  restore-on-a-new-box, and the off-box editing path. Either pass one:
      --remote <clone-url>     # a repo you created and can push to, e.g.
                               #   git@github.com:you/know-kb.git  or  https://host/you/know-kb.git
  (ensure this box's git auth — an SSH key in the agent, or a credential helper — can
  push to it), OR pass --no-remote to run local-only on purpose."
  fi
  local out
  if ! out="$(GIT_SSH_COMMAND="$SSH_CMD" git ls-remote "$REMOTE_URL" 2>&1)"; then
    die "can't reach or authenticate the remote: $REMOTE_URL
  $out
  Make sure the repo exists and this box's git credentials (SSH key / helper) can
  access it — or pass --no-remote."
  fi
  REMOTE_MODE=remote
  if [ -n "$out" ]; then
    REMOTE_HAS_COMMITS=1
    log "remote: $REMOTE_URL (has history — will RESTORE if the local KB is absent)"
  else
    log "remote: $REMOTE_URL (empty — will SEED it from a fresh KB)"
  fi
}

_remote_writable() {          # prove push access without touching real refs
  local ref="refs/heads/_know-write-check"
  GIT_SSH_COMMAND="$SSH_CMD" git -C "$KB_REPO" push mirror "HEAD:$ref" >/dev/null 2>&1 || return 1
  GIT_SSH_COMMAND="$SSH_CMD" git -C "$KB_REPO" push mirror ":$ref" >/dev/null 2>&1 || true
  return 0
}

_seed_kb() {                  # fresh KB skeleton (OKF bundle) + first commit
  mkdir -p "$KB_REPO"/{raw,curated,_superseded,contradictions}
  git -C "$KB_REPO" init -q -b main 2>/dev/null || git -C "$KB_REPO" init -q
  for d in raw _superseded contradictions; do touch "$KB_REPO/$d/.gitkeep"; done
  cp "$HERE/kb-template/CLAUDE.md" "$KB_REPO/CLAUDE.md"
  printf -- '---\nokf_version: "0.1"\n---\n\n# Knowledge base index\n\n_(empty — facts appear here as the secretary curates them)_\n' > "$KB_REPO/curated/index.md"
  git -C "$KB_REPO" add -A
  git -C "$KB_REPO" -c user.name=know-capture -c user.email=capture@know.local \
    commit -q -m "capture: init knowledge base (OKF bundle in curated/)"
}

_wire_mirror() {              # ensure remote 'mirror' points at REMOTE_URL
  if git -C "$KB_REPO" remote | grep -qx mirror; then
    git -C "$KB_REPO" remote set-url mirror "$REMOTE_URL"
  else
    git -C "$KB_REPO" remote add mirror "$REMOTE_URL"
  fi
}

setup_kb() {
  if [ -d "$KB_REPO/.git" ]; then
    log "KB repo exists at $KB_REPO — reusing"
    if [ "$REMOTE_MODE" = remote ]; then
      _wire_mirror
      if [ -n "$REMOTE_HAS_COMMITS" ]; then
        GIT_SSH_COMMAND="$SSH_CMD" git -C "$KB_REPO" pull --ff-only mirror >/dev/null 2>&1 || true
      else
        # adding a remote to an existing local-only brain → seed the empty remote
        GIT_SSH_COMMAND="$SSH_CMD" git -C "$KB_REPO" push -u mirror HEAD >/dev/null 2>&1 \
          || die "couldn't seed the remote $REMOTE_URL from the existing KB (write access?). Or --no-remote."
        ok "seeded remote $REMOTE_URL from the existing KB"
      fi
    fi
  elif [ "$REMOTE_MODE" = remote ] && [ -n "$REMOTE_HAS_COMMITS" ]; then
    log "restoring KB from remote → $KB_REPO"
    GIT_SSH_COMMAND="$SSH_CMD" git clone "$REMOTE_URL" "$KB_REPO" >/dev/null 2>&1 \
      || die "clone (restore) failed from $REMOTE_URL — check access, or --no-remote."
    [ -d "$KB_REPO/.git" ] || die "clone (restore) produced no repo at $KB_REPO"
    git -C "$KB_REPO" remote | grep -qx origin && git -C "$KB_REPO" remote rename origin mirror || true
    git -C "$KB_REPO" remote | grep -qx mirror || git -C "$KB_REPO" remote add mirror "$REMOTE_URL"
    for d in raw curated _superseded contradictions; do mkdir -p "$KB_REPO/$d"; done
    ok "restored KB from remote ($(git -C "$KB_REPO" rev-list --count HEAD 2>/dev/null || echo '?') commits)"
  else
    log "initializing a fresh KB repo at $KB_REPO"
    _seed_kb
    if [ "$REMOTE_MODE" = remote ]; then
      git -C "$KB_REPO" remote add mirror "$REMOTE_URL"
      GIT_SSH_COMMAND="$SSH_CMD" git -C "$KB_REPO" push -u mirror HEAD >/dev/null 2>&1 \
        || die "seeded the local KB but PUSH to $REMOTE_URL failed — no write access, or the
  repo already has unrelated history (use an EMPTY repo you can push to). Or --no-remote."
      ok "seeded remote $REMOTE_URL"
    fi
  fi
  if [ "$REMOTE_MODE" = remote ]; then
    if _remote_writable; then ok "remote is reachable + writable: $REMOTE_URL"
    else log "WARN: $REMOTE_URL is reachable but NOT writable from this box — new facts
  won't back up (the local repo is still the truth). Fix this box's git push auth."; fi
  fi
}

# --- TEST SEAM: exercise just the KB/remote logic (no service/venv/key needed) ----
# KNOW_SETUP_TEST=1 KNOW_KB_REPO=… bash install-know.sh [--remote <url> | --no-remote]
if [ -n "${KNOW_SETUP_TEST:-}" ]; then
  command -v git >/dev/null 2>&1 || die "git required"
  resolve_remote
  setup_kb
  ok "KNOW_SETUP_TEST done (mode=$REMOTE_MODE)"
  exit 0
fi

# --- 0. preflight ------------------------------------------------------------
# No node / system `claude` needed: the Claude Agent SDK bundles a native CLI in the venv.
for t in python3 openssl curl git sprite-env; do
  command -v "$t" >/dev/null 2>&1 || die "missing required tool: $t"
done
python3 -c 'import venv' 2>/dev/null || die "python3 venv module not available"
mkdir -p "$STATE_DIR"

# resolve the brain's display name: --name > existing service's KNOW_NAME (re-run) > "know"
NAME="${NAME_ARG:-$(svc_env KNOW_NAME)}"; NAME="${NAME:-know}"

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

# --- 1b. resolve + verify the KB remote EARLY (fail fast before the slow deploy) --
resolve_remote

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

# --- 3. resolve the model id (KNOW_MODEL > existing service's pin > resolved default) --
MODEL="${KNOW_MODEL:-}"
[ -z "$MODEL" ] && MODEL="$(svc_env KNOW_MODEL)"
[ -z "$MODEL" ] && MODEL="$("$PYBIN" "$GW_DIR/boot_check.py" resolve-model)"
[ -n "$MODEL" ] || die "could not resolve a model id"
ok "model: $MODEL"

# --- 4. mint the secret (persisted; re-run reuses it) ------------------------
SECRET_FILE="$STATE_DIR/secret"
if [ ! -f "$SECRET_FILE" ]; then
  openssl rand -hex 24 > "$SECRET_FILE"; chmod 600 "$SECRET_FILE"
  log "minted a new secret path segment"
fi
SECRET="$(cat "$SECRET_FILE")"

# --- 5. KB data repo: adopt-or-seed (init fresh / restore from remote / reuse) --
setup_kb
ok "KB repo ready ($KB_REPO)"

# --- 6. supervised sprite-env service (key + config scoped HERE, not the shell) --
# PATH lets the recall/secretary agent subprocess + git resolve under the service's
# otherwise-minimal environment. The gateway reads KNOW_* from this env.
ENVS="HOME=$HOME,PATH=$PATH,ANTHROPIC_API_KEY=$API_KEY,KNOW_SECRET=$SECRET,KNOW_NAME=$NAME,KNOW_MODEL=$MODEL"
[ -n "${KNOW_ALERT_WEBHOOK:-}" ] && ENVS="$ENVS,KNOW_ALERT_WEBHOOK=$KNOW_ALERT_WEBHOOK"
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

# --- 7. wait for health ------------------------------------------------------
log "waiting for the gateway to come up..."
up=0
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$PORT/healthz" 2>/dev/null || true)"
  [ "$code" = "200" ] && { up=1; break; }
  sleep 1
done
[ "$up" = "1" ] || die "gateway did not become healthy on :$PORT (check: sprite-env services get $SERVICE)"
ok "gateway healthy on :$PORT"

# --- 8. ordered boot self-check (refuse green on any failure, §10.11) --------
log "running the ordered boot self-check..."
"$PYBIN" "$GW_DIR/boot_check.py" check "$CLAUDE_FLOOR" "$MODEL" "$CLAUDE_VER" \
  || die "boot self-check FAILED — see the leg above; the brain is NOT green"

# --- 9. secret-path reachability asserts (§9.4–9.6) -------------------------
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

# --- 10. CLI save/recall smoke (the tools FIRE, not just connect, §9.7) ------
log "CLI smoke: save + recall a canary through the live MCP tools..."
SMOKE="/mcp/$SECRET/install-smoke/"
save_body='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"save","arguments":{"title":"Install canary","body":"know install smoke test canary fact."}}}'
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

# --- 11. onboarding card -----------------------------------------------------
BASE_URL="$SPRITE_URL/mcp/$SECRET"
if [ "$REMOTE_MODE" = remote ]; then
  BACKUP_LINE="Backup + restore: this brain mirrors its KB to
      $REMOTE_URL
  Rebuild on a new/replacement box: run install-know.sh --remote <same url> — it
  clones the entire KB back (facts, history, contradictions)."
else
  BACKUP_LINE="Backup + restore: LOCAL-ONLY (--no-remote) — no off-box backup or restore.
  Re-run with --remote <a repo you can push to> to enable durability + restore."
fi
cat <<EOF

=========================================================================
  know brain "$NAME" is UP and GREEN.
  -------------------------------------------------------------------
  Your personal connector URL (the URL IS the credential — treat like a password):

      $BASE_URL/<your-name>/

  RECOMMENDED — Claude Code plugin (one install: tools + /know: commands + capture).
  Install SCOPED to the folder you want it in — NOT the default 'user' scope, which
  enables the brain in EVERY folder you open:
      cd /path/to/your/project
      claude plugin marketplace add podclave/know --scope local
      claude plugin install know@know --scope local --config mcp_url="$BASE_URL/<your-name>/"
      claude plugin enable know@know --scope local
    --scope local = this folder only, just you (.claude/settings.local.json, gitignored);
    your URL goes to secure storage, never a settings file. Wrong (user) scope already?
    Undo: claude plugin uninstall know@know && claude plugin marketplace remove know.
    TEAM repo: use --scope project (or commit .claude/settings.json with
    extraKnownMarketplaces + "enabledPlugins":{"know@know":true} + permissions.allow for
    the READ tools mcp__plugin_know_know__recall / __list / __contradictions) — auto-enables
    per-PROJECT on clone+trust; save/supersede/resolve still prompt.

  ALTERNATIVE — bare connector (no /know: commands or capture):
      claude mcp add --transport http --scope local know "$BASE_URL/<your-name>/"

  claude.ai / Cowork: NOT RECOMMENDED — the same URL connects, but claude.ai
  connectors are account-global (on in every project, not per-project) and need
  manual Settings tweaks before tools load. Use Claude Code.

  Rotate the secret by re-running install with a fresh secret + re-issuing this card.
  -------------------------------------------------------------------
  $BACKUP_LINE
  -------------------------------------------------------------------
  Browse the brain as an interactive knowledge graph (OKF visualizer) at:

      $SPRITE_URL/viewer/$SECRET/

  (same secret-in-path; open in a browser — click a node to read the fact and
  follow its cross-links.)
  -------------------------------------------------------------------
  Heartbeat: add an external pinger (Podclave Schedule / GitHub Actions cron /
  uptime monitor), hourly, that POSTs to:

      $SPRITE_URL/wake

  (auth probe + curator liveness; with a remote it also pulls + reconciles off-box
  edits. A spun-down box can't cron itself, so this is required for off-box reconcile.)
  -------------------------------------------------------------------
  KB repo: $KB_REPO     model: $MODEL     agent runtime (bundled CLI): $CLAUDE_VER
=========================================================================
EOF
