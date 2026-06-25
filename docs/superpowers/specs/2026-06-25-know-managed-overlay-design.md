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
action**, plus an installer card block that points the admin at the templates and prints
this brain's `KNOW_HOST`/`KNOW_SECRET` values to paste into the one env file.

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

- **Managed settings** live at `/etc/claude-code/managed-settings.json` (single file) or
  `/etc/claude-code/managed-settings.d/*.json` (drop-in directory), plus
  `/etc/claude-code/managed-mcp.json` for MCP (Linux). The managed tier is
  highest-precedence and cannot be overridden by user/project settings.
- **`managed-settings.d/` drop-in directory** is confirmed (docs + the 2.1.191 binary):
  each file is a full settings object; files merge in **lexical filename order**; later
  files **override scalars, concatenate arrays, and deep-merge objects**. `hooks`,
  `permissions`, and `${VAR}` expansion behave identically there. Using a drop-in file
  (e.g. `50-know.json`) means our entries **coexist** with any settings Podclave itself
  manages, and our `permissions.allow` array **concatenates** with existing entries rather
  than replacing them — the reason to prefer `.d/` over editing a shared
  `managed-settings.json`.
- **No `managed-mcp.d/` drop-in exists** — MCP servers are documented only in the single
  `/etc/claude-code/managed-mcp.json`. Whether `mcpServers` is honored inside a
  `managed-settings.d/*.json` file is **undocumented** (settings files normally don't
  carry `mcpServers`); treat declaring MCP in the drop-in as an unverified optimization,
  not the default.
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
# The ONE place the admin sets the overlay's env. managed-mcp.json expands all three.
export KNOW_HOST="<brain-host>"        # host only, no scheme
export KNOW_SECRET="<shared-secret>"   # the shared team secret
export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"
```

`KNOW_HOST` and `KNOW_SECRET` are the brain's, admin-filled (the installer card prints the
values) — **no default**, so a misconfigured box yields a plainly broken URL (visible)
rather than silently routing somewhere wrong. `KNOW_USER` bridges `~/.podclave/user-email`
into an env var (managed settings expand env vars, not files); `|| echo anonymous` keeps a
missing file from producing a broken URL — attribution degrades to `anonymous`. Putting all
three here means the admin edits **one file**; the JSON templates are copied verbatim.

### 2. Connector — `/etc/claude-code/managed-mcp.json`

```json
{
  "mcpServers": {
    "know": {
      "type": "http",
      "url": "https://${KNOW_HOST}/mcp/${KNOW_SECRET}/${KNOW_USER:-anonymous}/"
    }
  }
}
```

Per-user attribution with no plugin, no typing, no keychain — and **no per-deploy
placeholders**: the URL is fully env-driven from `know-identity.sh`, so this file is copied
verbatim. The shared secret in `/etc` is acceptable — it is the same team secret every
user's connector URL would carry anyway; it grants no more than the per-user URLs already
do (one brain per box). An email as
the path segment routes fine (`@`/`.` are legal `pchar`; Starlette URL-decodes either the
raw `@` or a `%40`-encoded form to the same attribution).

**This stays a single file** — there is no `managed-mcp.d/` drop-in for MCP. If Podclave
(or another tool) already manages `/etc/claude-code/managed-mcp.json`, the admin **merges
the `know` entry into the existing `mcpServers` object** rather than overwriting the file.
*Optional, verify-then-use:* if a later check confirms `mcpServers` is honored inside a
`managed-settings.d/*.json` drop-in (see Background), the whole overlay can collapse into
drop-in files and never touch the shared `managed-mcp.json` — but the default design keeps
MCP in `managed-mcp.json` since the drop-in route is undocumented.

### 3. Permissions + nudge — `/etc/claude-code/managed-settings.d/50-know.json`

A **drop-in** settings file (not the shared `managed-settings.json`), so it coexists with
anything Podclave manages and its `permissions.allow` concatenates with existing entries.
The `50-` prefix is a neutral lexical position; our file only adds keys, so merge order is
not load-bearing.

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

### 4. Nudge deployment + placement source of truth

The nudge script is deployed to `/etc/claude-code/know/nudge.py`, copied verbatim from
the repo's single source of truth `client-plugin/nudge.py`. No second copy is committed.

**Placement lives in exactly one place: `examples/managed/output.sh`.** Placing files in a
Podclave org bundle is a manual process (the admin can't `cp` into a bundle from the
install host, and there's no reliable cross-host copy), so the overlay does NOT scatter
per-file `# BUNDLE LOCATION` comments (and JSON can't carry comments anyway). Instead
`output.sh` cats every file the admin needs — the three overlay templates **and**
`client-plugin/nudge.py` — each under a `# BUNDLE LOCATION: <path>` banner. The admin runs
it and pastes each block into the bundle at the path shown. The README and installer card
do not duplicate placement; they point at `output.sh`.

`output.sh` also **fills in the values**: pass `KNOW_HOST` and `KNOW_SECRET` (env vars; the
installer card prints a ready-to-paste `KNOW_HOST=… KNOW_SECRET=… bash examples/managed/output.sh`
command with this brain's values) and the emitted `know-identity.sh` block has them
substituted for the `<brain-host>`/`<shared-secret>` placeholders — so there's no separate
hand-edit step. Without them it emits the placeholder template. (`KNOW_USER` is always the
per-user runtime expression; the JSON files are emitted verbatim.)

## Deliverables

1. **`examples/managed/` (repo)** — the overlay templates + the placement lister:
   - `etc/claude-code/managed-mcp.json` (env-driven URL — no placeholders; copied verbatim)
   - `etc/claude-code/managed-settings.d/50-know.json` (the permissions + hook block above)
   - `etc/profile.d/know-identity.sh` (the one place env is set: `KNOW_HOST`/`KNOW_SECRET`/`KNOW_USER`)
   - `output.sh` (the **single source of placement**: cats each of the above + `client-plugin/nudge.py`
     under a `# BUNDLE LOCATION: <path>` banner for manual paste into the bundle)
   - `README.md` — what each file does (no per-file destinations — those come from `output.sh`),
     the one-file-to-edit model, the `managed-settings.d/` merge behavior, and the
     "merge the `know` entry into an existing `managed-mcp.json`" note.

2. **Top-level `README.md` section** — "Org-wide zero-setup provisioning (Podclave /
   managed settings)": explains the model (admin drops files into a Podclave org bundle;
   users do nothing), the one-file env model, the placed files + the nudge copy, the
   reads-and-writes auto-allow rationale, and the two documented assumptions (profile.d env
   inheritance; exact managed paths per CC version). Cross-links `examples/managed/`.
   Positioned as an alternative to the per-user plugin / bare-connector paths, not a replacement.

3. **Installer onboarding-card block (`server/install-know.sh`)** — a new **"Org admin
   overlay"** section in the printed card. It does NOT repeat the template file contents
   (those come from `examples/managed/output.sh`); it tells the admin to run `output.sh`
   and prints THIS brain's values to paste into `know-identity.sh`: `KNOW_HOST` (host from
   `$SPRITE_URL`, scheme stripped) and `KNOW_SECRET` (`$SECRET`). Gated to print always
   (harmless guidance), appended after the connect/visualizer/heartbeat sections.

## Data flow (after)

```
Admin (once, into a Podclave org bundle):
  bash examples/managed/output.sh   → prints each file under "# BUNDLE LOCATION: <path>";
                                       paste each block into the bundle at that path
  set KNOW_HOST + KNOW_SECRET in the bundle's know-identity.sh (values from the install card)

End user (zero action):
  launch `claude`
    └─ $KNOW_USER resolved from ~/.podclave/user-email
        └─ managed-mcp.json → connector at …/<secret>/<email>/  (tools available, no prompt)
        └─ managed-settings.d/50-know.json → reads+writes auto-allowed; nudge hook armed
            └─ recall on ask; commit-nudge proposes durable facts; user approves; save
```

## Testing

This deliverable is docs + static templates + a printed installer block — no runtime
logic. Verification:

- **Template validity:** the committed `examples/managed/etc/claude-code/managed-mcp.json`
  and `examples/managed/etc/claude-code/managed-settings.d/50-know.json` parse as JSON
  (e.g. `python3 -m json.tool`), and `examples/managed/etc/profile.d/know-identity.sh`
  passes `bash -n`. Add a standalone check (or a step in the install regression) that
  every committed `examples/managed/**/*.json` is valid JSON and the `.sh` is syntactically
  valid.
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
- **Managed file paths/filenames** (`managed-mcp.json`, `managed-settings.d/`) match the
  current docs and the 2.1.191 binary strings; verify against the installed CC version
  before publishing.
- **`managed-settings.d/` vs sibling `managed-settings.json` precedence is undocumented.**
  We sidestep it by using **only** the `.d/` drop-in (we never write a sibling
  `managed-settings.json`), so there is no ambiguity in our own footprint.
- **`mcpServers` inside a settings drop-in is undocumented.** The default keeps MCP in
  `managed-mcp.json`. If an implement-time check (`claude doctor` / tools available on a
  test box) confirms a drop-in `mcpServers` loads, the overlay MAY collapse to drop-in
  files only — but that is an optional optimization, not the shipped default.
- **Email-as-path-segment:** confirmed routable, but the templates note that if a future
  client URL-encodes differently, attribution still resolves server-side.
