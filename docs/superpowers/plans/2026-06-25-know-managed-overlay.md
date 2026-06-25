# know Managed-Settings Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an org-admin "overlay" that provisions every Podclave user with the `know` connector + commit-nudge at zero per-user setup, via Claude Code managed settings — as committed example templates, a validity check, a README section, and an installer onboarding-card block.

**Architecture:** Static admin files only: a `/etc/profile.d` bridge turns the per-user identity file `~/.podclave/user-email` into `$KNOW_USER`; `/etc/claude-code/managed-mcp.json` expands it into a per-user connector URL; a `/etc/claude-code/managed-settings.d/50-know.json` drop-in auto-allows the `know` tools and arms the nudge hook. The repo carries these as templates under `examples/managed/` (mirroring deploy paths), a bash validity check, and an installer card block that prints them pre-filled with the brain's host + secret. No gateway/runtime code changes.

**Tech Stack:** Static JSON + a POSIX `sh` snippet, a bash test script, `python3` (for JSON parsing in the check), the existing `server/install-know.sh` bash installer, GitHub Actions.

## Global Constraints

- **Managed MCP server name is `know`** → its tools are `mcp__know__<tool>` (NOT the plugin's `mcp__plugin_know_know__<tool>`).
- **All six gateway tools are auto-allowed:** `recall`, `save`, `list`, `supersede`, `contradictions`, `resolve` — i.e. exactly `mcp__know__recall/save/list/supersede/contradictions/resolve` (writes included; the `save` tool description already gates on in-conversation approval).
- **Connector URL form:** `https://<brain-host>/mcp/<shared-secret>/${KNOW_USER:-anonymous}/`.
- **Identity bridge:** `export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"`.
- **MCP stays in the single `managed-mcp.json`** (there is no `managed-mcp.d/`); settings ship as the **drop-in** `managed-settings.d/50-know.json`.
- **`nudge.py` has one source of truth:** `client-plugin/nudge.py`. Do NOT commit a second copy anywhere (the overlay references copying it to `/etc/claude-code/know/nudge.py`).
- **`examples/managed/` mirrors deploy paths** under an `etc/` subtree so an admin can nearly `cp -r examples/managed/etc/* /etc/`.
- **The installer card heredoc is unquoted (`cat <<EOF`)** → any literal `${...}` that must appear in the printed output (e.g. `${KNOW_USER:-anonymous}`) MUST be written escaped as `\${...}`, while real installer vars (`$SPRITE_URL`, `$SECRET`) expand normally.
- **Don't disturb the green suites:** `bash server/test-install-know.sh` (24 passed) and `bash -n server/install-know.sh`.

---

### Task 1: Overlay templates + validity check

**Files:**
- Create: `examples/managed/etc/claude-code/managed-mcp.json`
- Create: `examples/managed/etc/claude-code/managed-settings.d/50-know.json`
- Create: `examples/managed/etc/profile.d/know-identity.sh`
- Create: `examples/managed/README.md`
- Create (test): `server/test-managed-overlay.sh`

**Interfaces:**
- Consumes: the gateway tool names declared in `server/gateway/mcp_endpoint.py` (via the `_t("<name>", …)` calls) — the validity check reads these to assert parity.
- Produces: the committed overlay templates and `server/test-managed-overlay.sh` (a standalone bash check, exit 0 on success), which Task 3 wires into CI.

- [ ] **Step 1: Write the failing validity check**

Create `server/test-managed-overlay.sh`:

```bash
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash server/test-managed-overlay.sh; echo "exit=$?"`
Expected: FAIL — prints `missing …/examples/managed` (the dir doesn't exist yet) and `exit=1`.

- [ ] **Step 3: Create the connector template**

Create `examples/managed/etc/claude-code/managed-mcp.json`:

```json
{
  "mcpServers": {
    "know": {
      "type": "http",
      "url": "https://<brain-host>/mcp/<shared-secret>/${KNOW_USER:-anonymous}/"
    }
  }
}
```

- [ ] **Step 4: Create the settings drop-in**

Create `examples/managed/etc/claude-code/managed-settings.d/50-know.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__know__recall",
      "mcp__know__list",
      "mcp__know__contradictions",
      "mcp__know__save",
      "mcp__know__supersede",
      "mcp__know__resolve"
    ]
  },
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 /etc/claude-code/know/nudge.py" } ] }
    ]
  }
}
```

- [ ] **Step 5: Create the identity bridge**

Create `examples/managed/etc/profile.d/know-identity.sh`:

```sh
# /etc/profile.d/know-identity.sh
# Expose the Podclave per-user identity (the file ~/.podclave/user-email) as $KNOW_USER,
# so /etc/claude-code/managed-mcp.json can expand it into each user's connector URL.
# Missing file -> "anonymous" (a valid, generic URL) rather than a broken one.
export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"
```

- [ ] **Step 6: Create the overlay README**

Create `examples/managed/README.md`:

```markdown
# know org-wide overlay (Podclave / Claude Code managed settings)

Provision every org user with the `know` connector + commit-nudge at **zero per-user
setup**. As the Podclave org admin, place these static files on the managed Claude Code
image. Users do nothing — `claude` just has `know` on first launch.

This directory mirrors the deploy paths, so you can almost:

    cp -r examples/managed/etc/* /etc/

Then copy the nudge script (kept single-source in this repo, not duplicated here):

    install -D -m 0644 client-plugin/nudge.py /etc/claude-code/know/nudge.py

## Files

- `etc/profile.d/know-identity.sh` → `/etc/profile.d/know-identity.sh`
  Bridges the per-user identity **file** `~/.podclave/user-email` into the env var
  `$KNOW_USER` (managed settings expand env vars, not files). Missing file → `anonymous`.

- `etc/claude-code/managed-mcp.json` → `/etc/claude-code/managed-mcp.json`
  The per-user connector. Replace `<brain-host>` and `<shared-secret>` with your brain's
  (the installer's onboarding card prints this file already filled in). **There is no
  `managed-mcp.d/` drop-in** — if Podclave already manages this file, merge the `know`
  entry into the existing `mcpServers` object instead of overwriting it.

- `etc/claude-code/managed-settings.d/50-know.json` → `/etc/claude-code/managed-settings.d/50-know.json`
  A **drop-in** settings file: auto-allows the six `know` tools (so recall/save never
  prompt — the curation gate is the in-conversation approval the model already requires)
  and arms the commit-nudge `UserPromptSubmit` hook. Drop-in files merge in lexical order,
  and `permissions.allow` **concatenates** with anything else managed, so this coexists
  with other managed settings rather than replacing them.

## Verify after deploy

On a test box: `claude doctor`, then launch `claude` and confirm the `know` tools are
present without a prompt. If the URL shows `…/anonymous/`, the session didn't inherit the
`profile.d` env — set `KNOW_USER` wherever Podclave sources session environment.
```

- [ ] **Step 7: Run the validity check to verify it passes**

Run: `bash server/test-managed-overlay.sh; echo "exit=$?"`
Expected: PASS — all checks `PASS`, `RESULT: N passed, 0 failed`, `exit=0`.

- [ ] **Step 8: Confirm the gateway-parity check is real (sanity)**

Run: `grep -oE '_t\("[a-z]+"' server/gateway/mcp_endpoint.py | sort -u`
Expected: shows `_t("recall"`, `_t("save"`, `_t("list"`, `_t("supersede"`, `_t("contradictions"`, `_t("resolve"` — the same six the drop-in allows. (This confirms the check in Step 1 is comparing against the real surface.)

- [ ] **Step 9: Commit**

```bash
git add examples/managed server/test-managed-overlay.sh
git commit -m "Org overlay: managed-settings.d templates + validity check"
```

---

### Task 2: Installer onboarding-card "Org admin overlay" block

**Files:**
- Modify: `server/install-know.sh` (the onboarding-card heredoc near the end — add a new block after the Heartbeat section, before the final `KB repo:` line)

**Interfaces:**
- Consumes: the installer's existing `$SPRITE_URL`, `$SECRET`, `$PYBIN`, `$GW_DIR` variables (all defined earlier in the script).
- Produces: printed, copy-paste-ready overlay content filled with this brain's host + secret.

- [ ] **Step 1: Read the current card heredoc**

Run: `sed -n '360,430p' server/install-know.sh`
Confirm the onboarding card is a single unquoted `cat <<EOF … EOF` block, that `$SPRITE_URL` and `$SECRET` are in scope, and locate the Heartbeat block + the final `KB repo:` line (you'll insert between them).

- [ ] **Step 2: Add the "Org admin overlay" block to the card**

Inside the `cat <<EOF` heredoc, immediately AFTER the Heartbeat block's closing separator line and BEFORE the `  KB repo: …` line, insert this text. NOTE the escaping: real installer vars (`$SPRITE_URL`, `$SECRET`, `$PYBIN`, `$GW_DIR`) expand; the literal `\${KNOW_USER:-anonymous}` is escaped so it prints verbatim (the heredoc is unquoted).

```bash
  -------------------------------------------------------------------
  ORG ADMINS (Podclave): provision EVERY user with zero setup — no plugin, no URL paste.
  As the org admin, drop these static files on the managed Claude Code image:

  1) /etc/profile.d/know-identity.sh   (turns the per-user identity file into an env var)
       export KNOW_USER="\$(cat "\$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"

  2) /etc/claude-code/managed-mcp.json   (per-user connector; merge into it if it exists)
       {
         "mcpServers": {
           "know": {
             "type": "http",
             "url": "$SPRITE_URL/mcp/$SECRET/\${KNOW_USER:-anonymous}/"
           }
         }
       }

  3) /etc/claude-code/managed-settings.d/50-know.json   (auto-allow know tools + nudge hook)
       {
         "permissions": { "allow": [
           "mcp__know__recall","mcp__know__list","mcp__know__contradictions",
           "mcp__know__save","mcp__know__supersede","mcp__know__resolve" ] },
         "hooks": { "UserPromptSubmit": [ { "hooks": [
           { "type": "command", "command": "python3 /etc/claude-code/know/nudge.py" } ] } ] }
       }

  4) Deploy the nudge script:
       install -D -m 0644 client-plugin/nudge.py /etc/claude-code/know/nudge.py

  Templates + details: examples/managed/ in the know repo. (Recall/save then work with no
  prompt; the secret in the URL is the same shared team secret — treat the file accordingly.)
```

- [ ] **Step 3: Verify installer syntax**

Run: `bash -n server/install-know.sh && echo "syntax ok"`
Expected: `syntax ok`.

- [ ] **Step 4: Verify the card renders with vars expanded and the literal kept**

Run this focused render check (exercises the same heredoc by sourcing a stubbed tail is overkill; instead grep the source to confirm the escaping is correct):

```bash
grep -n 'KNOW_USER:-anonymous' server/install-know.sh
```
Expected: the matches inside the card show `\${KNOW_USER:-anonymous}` (backslash-escaped) — NOT a bare `${KNOW_USER:-anonymous}` (which the unquoted heredoc would expand to `anonymous` at print time). The identity-bridge line (item 1) also shows `\$(cat …)` / `\$HOME` escaped.

- [ ] **Step 5: Confirm the install regression still passes**

Run: `bash server/test-install-know.sh 2>&1 | tail -2`
Expected: `RESULT: 24 passed, 0 failed` (the card block is print-only and downstream of the `KNOW_SETUP_TEST` seam exit, so the harness is unaffected).

- [ ] **Step 6: Commit**

```bash
git add server/install-know.sh
git commit -m "installer: print an Org admin overlay block (pre-filled managed-settings)"
```

---

### Task 3: README section + CI wiring

**Files:**
- Modify: `README.md` (add a new section)
- Modify: `.github/workflows/test.yml` (run `server/test-managed-overlay.sh`)

**Interfaces:**
- Consumes: `server/test-managed-overlay.sh` from Task 1.
- Produces: user-facing docs + CI coverage of the overlay templates.

- [ ] **Step 1: Add the README section**

In `README.md`, add a new section. Place it after the "Connect (Claude Code)" section and before "Browse the brain (OKF visualizer)" (read the file first to find the exact boundary and match heading style). Insert:

```markdown
## Org-wide zero-setup provisioning (Podclave / managed settings)

Running an org? Instead of each teammate installing the plugin or pasting a URL, an admin
can provision **every** user at once with Claude Code **managed settings** — users do
nothing and `know` is just there on first launch.

The per-user identity lives in the file `~/.podclave/user-email`. Because managed settings
expand environment variables (not files), a tiny `/etc/profile.d` bridge turns it into
`$KNOW_USER`, which the connector URL templates per user:

1. **`/etc/profile.d/know-identity.sh`** — `export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"`
2. **`/etc/claude-code/managed-mcp.json`** — the connector, `https://<brain-host>/mcp/<secret>/${KNOW_USER:-anonymous}/` (one shared file; no `managed-mcp.d/` exists — merge the `know` entry in if the file is already managed).
3. **`/etc/claude-code/managed-settings.d/50-know.json`** — a drop-in that auto-allows the six `know` tools (recall/save never prompt; the curation gate is the in-conversation approval) and arms the commit-nudge `UserPromptSubmit` hook. Drop-in files merge in lexical order and `permissions.allow` concatenates, so it coexists with other managed settings.
4. Copy the nudge script: `install -D -m 0644 client-plugin/nudge.py /etc/claude-code/know/nudge.py`.

Ready-to-use templates (mirroring the deploy paths) live in [`examples/managed/`](examples/managed/),
and the installer's onboarding card prints all of the above **already filled in** with your
brain's host + secret. This is an alternative to the per-user plugin / bare-connector paths
above, not a replacement. The `/know:*` slash commands are not provisioned this way (they
need the plugin); the nudge + natural language already drive recall/save/commit.

Two things to verify on a test box: that the `claude` session inherits the `profile.d`
env (else the URL falls back to `…/anonymous/` — set `KNOW_USER` wherever Podclave sources
session env), and the managed-file paths against your installed Claude Code version.
```

- [ ] **Step 2: Wire the validity check into CI**

In `.github/workflows/test.yml`, add a step to the `install-script` job (which already runs bash checks with no venv). Read the file first; after the existing `install-know.sh regression` step, add:

```yaml
      - name: managed-overlay templates validity
        run: bash server/test-managed-overlay.sh
```

- [ ] **Step 3: Verify the CI step command works locally**

Run: `bash server/test-managed-overlay.sh; echo "exit=$?"`
Expected: `RESULT: N passed, 0 failed`, `exit=0`.

- [ ] **Step 4: Verify the workflow YAML is well-formed**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/test.yml')); print('yaml ok')"`
Expected: `yaml ok`. (If PyYAML isn't present, instead run `grep -n "managed-overlay" .github/workflows/test.yml` and confirm the step is nested under the `install-script` job's `steps:` at the right indentation.)

- [ ] **Step 5: Commit**

```bash
git add README.md .github/workflows/test.yml
git commit -m "docs+CI: org overlay README section and templates validity check"
```

---

## Final verification (after all tasks)

- [ ] `bash server/test-managed-overlay.sh` → `RESULT: N passed, 0 failed`.
- [ ] `bash server/test-install-know.sh` → `24 passed`.
- [ ] `bash -n server/install-know.sh` → ok.
- [ ] `grep -n 'KNOW_USER:-anonymous' server/install-know.sh` → card occurrences are backslash-escaped (`\${KNOW_USER:-anonymous}`).
- [ ] `find examples/managed -name nudge.py` → no output (single-source preserved).
- [ ] `python3 -m json.tool examples/managed/etc/claude-code/managed-mcp.json` and `… managed-settings.d/50-know.json` → both parse.

## Notes / decisions locked in this plan

- **MCP stays in `managed-mcp.json`** (no `managed-mcp.d/`); settings use the `.d/` drop-in. The "`mcpServers` inside a settings drop-in" optimization is intentionally NOT implemented (undocumented) — it's left as a note in the spec only.
- **Writes are auto-allowed** alongside reads (user decision): the `save` tool already requires explicit in-conversation approval, so a Claude Code permission prompt would be redundant.
- **`/know:*` commands are out of scope** (plugin-dependent).
