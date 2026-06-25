# know — Org-wide Zero-Setup Provisioning (Managed-Settings Overlay) Design

**Date:** 2026-06-25
**Status:** Approved for planning
**Scope:** Docs + example templates + an installer onboarding-card addition. No gateway/runtime code changes.

## Problem

Standing up a `know` brain produces good per-user connect instructions, but every
teammate still has to install the plugin (or add the connector) and paste their personal
URL. A Podclave **org admin** can place static files on the org's managed Claude Code
boxes (e.g. under `/etc/claude-code/…` and `/etc/profile.d/…`), which is the better lever
than asking each user to configure their own client. The install flow never tells the
admin this — there's no "here's the overlay that provisions every user with zero setup"
version of the guidance.

This design adds that: a documented set of admin-placed static files that give every org
user the `know` connector **and** the commit-nudge curation UX with **zero per-user
action**, plus an installer card block that prints those files already filled in for the
brain just stood up.

## Goals

- Every org user gets a working, **per-user-attributed** `know` connector on first
  `claude` launch — no plugin install, no URL paste, no secure-storage entry.
- Recall is effortless (read tools auto-approved); the commit-nudge curation UX is
  present org-wide.
- Provisioning uses **only documented managed-settings capabilities** — no dependence on
  unconfirmed plugin auto-install or on pre-seeding a `sensitive` plugin `userConfig`.
- The installer hands the admin copy-paste-ready, brain-specific overlay files.

## Non-Goals

- The `/know:*` slash commands. They require the plugin; managed-settings plugin
  auto-install is unconfirmed and the sensitive `mcp_url` userConfig cannot be pre-seeded.
  The nudge hook + natural language + the (separately documented) plugin path already
  cover the core flow. Commands remain a future enhancement if managed plugin
  auto-install is later confirmed.
- Any gateway/server runtime change. The brain is unchanged; this is client-side
  provisioning + docs.
- Replacing the existing per-user plugin / bare-connector install paths. This is an
  additional, org-admin path documented alongside them.

## Background facts (researched/verified 2026-06-25)

- **Managed settings** live at `/etc/claude-code/managed-settings.json` and
  `/etc/claude-code/managed-mcp.json` (Linux), are the highest-precedence tier, and
  cannot be overridden by user/project settings.
- **MCP server `url` supports env-var expansion** (`${VAR}`, `${VAR:-default}`) evaluated
  per session — so one managed file yields per-user URLs.
- **`permissions.allow`** in managed settings auto-approves named tools org-wide.
- **Managed settings carry a `hooks` block** — a `UserPromptSubmit` hook can run a
  deployed script.
- **The Podclave per-user identity is a file**, `~/.podclave/user-email` (a plain email,
  e.g. `joenoon@gmail.com`), **not** an env var. `managed-mcp.json` expands env, not
  files — hence the bridge below.
- Tool namespace for a managed MCP server named `know` is `mcp__know__<tool>` (NOT the
  plugin's `mcp__plugin_know_know__<tool>`).

## Components

### 1. Identity bridge — `/etc/profile.d/know-identity.sh`

```sh
# Expose the Podclave per-user identity (a file) as an env var managed-mcp.json can expand.
export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"
```

Turns `~/.podclave/user-email` into `$KNOW_USER`. The `|| echo anonymous` keeps a missing
file from producing a broken URL — attribution degrades to `anonymous`, nothing breaks.

### 2. Connector — `/etc/claude-code/managed-mcp.json`

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

Per-user attribution with no plugin, no typing, no keychain. `<brain-host>` and
`<shared-secret>` are the brain's, baked in by the admin (or by the installer card). The
shared secret in `/etc` is acceptable — it is the same team secret every user's connector
URL would carry anyway; it grants no more than the per-user URLs already do. An email as
the path segment routes fine (`@`/`.` are legal `pchar`; Starlette URL-decodes either the
raw `@` or a `%40`-encoded form to the same attribution).

### 3. Permissions + nudge — `/etc/claude-code/managed-settings.json`

```json
{
  "permissions": {
    "allow": [
      "mcp__know__recall", "mcp__know__list", "mcp__know__contradictions",
      "mcp__know__save", "mcp__know__supersede", "mcp__know__resolve"
    ]
  },
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 /etc/claude-code/know/nudge.py" } ] }
    ]
  }
}
```

- **All six tools auto-approved**, including writes. This is safe because the `save` tool
  description requires explicit in-conversation user approval before the model calls it
  (the model never self-initiates a save), so the in-conversation approval IS the curation
  gate; a second Claude Code permission prompt would be pure redundant friction.
- **Nudge hook** runs the deployed `nudge.py`. It is stdlib-only and needs no connector
  URL (it only injects a reminder for the live model to propose facts), so it requires no
  per-user config. Its env tunables still apply (`KNOW_NUDGE`, `KNOW_NUDGE_MIN_TURNS`,
  `KNOW_NUDGE_GAP_TURNS`).

### 4. Nudge deployment

The nudge script is deployed to `/etc/claude-code/know/nudge.py`, copied verbatim from
the repo's single source of truth `client-plugin/nudge.py`. No second copy is committed to
the tree; the docs and the installer card both reference copying that file. This keeps the
managed and plugin nudge identical by construction.

## Deliverables

1. **`examples/managed/` (repo)** — the overlay templates, with placeholders:
   - `managed-mcp.json` (placeholders `<brain-host>`, `<shared-secret>`)
   - `managed-settings.json` (the permissions + hook block above)
   - `know-identity.sh` (the profile.d bridge)
   - `README.md` — a short readme for the dir: what each file is, where it goes
     (`/etc/claude-code/managed-mcp.json`, `/etc/claude-code/managed-settings.json`,
     `/etc/profile.d/know-identity.sh`), and the `nudge.py` copy step
     (`client-plugin/nudge.py` → `/etc/claude-code/know/nudge.py`).

2. **Top-level `README.md` section** — "Org-wide zero-setup provisioning (Podclave /
   managed settings)": explains the model (admin places static files; users do nothing),
   the identity bridge, the three placed files + the nudge copy, the reads-and-writes
   auto-allow rationale, and the two documented assumptions (profile.d env inheritance;
   exact managed paths per CC version). Cross-links `examples/managed/`. Positioned as an
   alternative to the existing per-user plugin / bare-connector paths, not a replacement.

3. **Installer onboarding-card block (`server/install-know.sh`)** — a new **"Org admin
   overlay"** section in the printed card that emits the overlay files **already filled in**
   with this brain's `$SPRITE_URL` host and `$SECRET`, plus the `${KNOW_USER}` template,
   the `managed-settings.json` block, the `know-identity.sh` line, and the one-line
   `nudge.py` deploy instruction. The admin can copy these straight onto the org image.
   This is gated to print always (it's guidance, harmless if the reader isn't an admin),
   appended after the existing connect/visualizer/heartbeat sections.

## Data flow (after)

```
Admin (once, on the org's managed Claude Code image):
  place /etc/profile.d/know-identity.sh         (file → $KNOW_USER)
  place /etc/claude-code/managed-mcp.json        (per-user connector URL)
  place /etc/claude-code/managed-settings.json   (auto-allow tools + nudge hook)
  copy  client-plugin/nudge.py → /etc/claude-code/know/nudge.py

End user (zero action):
  launch `claude`
    └─ $KNOW_USER resolved from ~/.podclave/user-email
        └─ managed-mcp.json → connector at …/<secret>/<email>/  (tools available, no prompt)
        └─ managed-settings.json → reads+writes auto-allowed; nudge hook armed
            └─ recall on ask; commit-nudge proposes durable facts; user approves; save
```

## Testing

This deliverable is docs + static templates + a printed installer block — no runtime
logic. Verification:

- **Template validity:** `managed-mcp.json` and `managed-settings.json` parse as JSON
  (e.g. `python3 -m json.tool`), and `know-identity.sh` passes `bash -n`. Add a tiny
  check to the existing install regression or a standalone check that the committed
  `examples/managed/*.json` are valid JSON and the `.sh` is syntactically valid.
- **Tool-name consistency:** the `permissions.allow` entries are exactly the six
  `mcp__know__*` names matching the gateway's tool surface
  (`recall/save/list/supersede/contradictions/resolve`) — assert this against
  `server/gateway/mcp_endpoint.py`'s `TOOLS` so the list can't silently drift.
- **Installer card:** `bash -n server/install-know.sh` stays clean; the existing
  `test-install-know.sh` stays green (the card block is print-only, downstream of the
  `KNOW_SETUP_TEST` seam exit, so it isn't exercised — confirm the seam still short-circuits
  before it).
- **Nudge parity:** the docs/installer reference `client-plugin/nudge.py` as the single
  source (no committed second copy) — a check that no `examples/managed/nudge.py` exists.

## Assumptions / risks (documented, not blocking)

- **profile.d env inheritance:** depends on how Podclave launches `claude`. If the session
  does not inherit the login/interactive shell env, `$KNOW_USER` is unset and the URL
  falls back to `…/anonymous/`. Mitigation: the `:-anonymous` fallback (graceful, not
  broken); the docs tell the admin to verify and, if needed, set `KNOW_USER` wherever
  Podclave sources session env.
- **Managed file paths/filenames** (`managed-mcp.json`, `managed-settings.json`) are per
  the current docs; the implementation note says to verify against the installed CC
  version before publishing.
- **Email-as-path-segment:** confirmed routable, but the templates note that if a future
  client URL-encodes differently, attribution still resolves server-side.
