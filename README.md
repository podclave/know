# know

A small, self-hosted **team brain**: one server per team/concern that gives every
teammate's Claude shared, durable memory. Ask a question and **recall** returns what
the team has learned; learn something durable and your Claude **saves** it. A
server-side **secretary** keeps the knowledge organized. The whole thing is a git repo
of one-fact-per-file markdown — the git repo is the truth — wrapped in an
MCP-over-HTTP server you connect to as a single URL.

**Claude Code is the home surface:** install the `know` plugin (one step — the MCP
connector + `/know:` commands + an opt-out nudge to commit learnings you approve) and point it at your personal
URL. claude.ai / Desktop / Cowork can connect to the same URL, but there a connector is
account-global and needs manual settings — prefer Claude Code (see Connect below).

> Standalone and open-source-able (its own repo). Inspired by — and lifting ~⅔ of its
> server scaffolding from — [podbrain](https://github.com/podclave/podbrain), but with
> a different engine: no vector DB, just git + markdown + a cheap `claude` agent.

## How it works

```
   scheduled wake (hourly) ──run──▶  wake.py  (pull mirror · reconcile off-box edits)
                                          │
   ┌──────────────────────────────────────▼─────────────────────────────┐
   │  BRAIN — one Sprite, a supervised FastAPI MCP-over-HTTP service       │
   │   • git repo of markdown facts = the truth  → optional remote backup │
   │   • recall   — a cheap `claude` agent greps/reads the repo            │
   │   • save/list/supersede — write tools, scrubbed + committed to git     │
   │   • secretary — a `claude` that promotes raw→curated, dedupes, queues  │
   │                 contradictions, regenerates INDEX (human edits win)    │
   └──────────────────────────────┬───────────────────────────────────────┘
                MCP over HTTP, no auth header — a SECRET in the URL PATH:
                       https://<brain-host>/mcp/<secret>/<name>/
        ┌────────────────────┬──────────────┴───────┬─────────────────────┐
   Claude Code          claude.ai              Desktop                 Cowork
   (add the URL)        (add the URL)          (add the URL)           (add the URL)
```

- **Auth = a secret in the URL path** (the capability-URL pattern, like a Slack
  webhook). MCP auth is optional and every connector surface accepts a no-auth URL —
  no bearer header (the web UIs have no field for one), no OAuth subsystem to age out.
  The `<name>` segment is self-asserted attribution stamped on saves.
- **The brain runs the Claude Agent SDK** and uses whatever Claude auth already works on the box — it makes no claims about auth and provisions nothing. Running a server agent on a personal subscription is technically fine but against the spirit of subscription auth; choose with eyes open.
- **Storage:** `raw/` (append-only capture) → `curated/` (the polished read path the
  secretary owns) → `_superseded/` (retired; nothing is ever `rm`'d). Methodology lives
  in the repo's own [`CLAUDE.md`](server/kb-template/CLAUDE.md).
- **`curated/` is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
  (OKF) bundle** — Google's vendor-neutral "LLM-wiki" spec: markdown concept docs with
  YAML frontmatter (`type`/`title`/`description`/`tags`/`timestamp`), an `index.md`, and
  inline markdown cross-links forming a knowledge graph. The secretary writes the docs +
  links; deterministic code guarantees conformance (backfills `type`, regenerates the
  index, validates links). So the curated brain can be read by any OKF tool — e.g.
  rendered as an interactive graph by the OKF static visualizer — with zero lock-in.

## Install (stand up a brain)

On a **public** Sprite (or any host — see below) with a working `claude` on the box:

```bash
bash server/install-know.sh [--name <label>] [--remote <clone-url> | --no-remote]
```

You must either point the brain at a git remote it can push to — `--remote <clone-url>`
(any host; a repo you created and can push to) — or pass `--no-remote` to run local-only
on purpose. That remote is your backup **and** your restore source (see **Backup &
restore** below); the installer verifies it before doing the slow work, and fails fast
with help if it's missing or unreachable. A re-run needs neither flag (it reuses the
wired remote) and preserves the existing `--name`.

Idempotent — safe to re-run; standing up brain #N is the same command on a fresh host.
No Node or system `claude` needed: the agent runtime is the **Claude Agent SDK's bundled
native CLI**, installed into the gateway venv by `pip` — self-contained, version-pinned
by the SDK, and isolated from any interactive `claude` on the box. The installer pins the
cheapest dated model id + records the bundled CLI version, mints the secret, sets up the KB
git repo (seed a fresh one, restore from your remote, or `--no-remote`), creates the supervised service, runs an **agent-runtime check** (SDK bundled CLI) plus a real save+recall smoke (which warns, not dies, if the agent can't run), and prints an onboarding card with your connect URL.

Because the runtime is just a `pip install` (no Node, no global CLI, no `claude update`),
the same script stands a brain up on a plain VM — e.g. a DigitalOcean droplet — not only a
Sprite. (The `sprite-env` service wrapper is the one Sprite-specific piece; on another host
run the gateway under any supervisor.)

Flags: `--name <label>` (display name; default `know`), `--remote <clone-url>` / `--no-remote`.
Env: `KNOW_MODEL=<id>` (pin a specific model on (re)install), `KNOW_ALERT_WEBHOOK=<slack-webhook>`
(alert on reconcile failures).

## Backup & restore (the git remote)

The KB is always a local git repo — *the truth*. Point it at a remote and that remote
becomes both a **backup** (every save/curation pushes to it) and a **restore source**:

- **Empty remote** → the installer seeds it from a fresh KB.
- **Existing remote (has history)** → the installer **clones it back**. So if a box dies,
  re-running `install-know.sh --remote <same url>` stands up a replacement with the whole
  KB — facts, history, contradictions — restored.
- **`--no-remote`** → explicit local-only: no backup, no restore, no off-box editing.

You bring the repo; the installer **verifies** it (reachable, and a real push succeeds) but
never creates one for you. Any host works — GitHub, GitLab, self-hosted — via `git@…` or
`https://…`. If the box can't push yet, an interactive install generates an SSH **deploy
key** and walks you through adding it (on GitHub: the repo's Settings → Deploy keys, with
write access) — a least-privilege, per-box credential scoped to that one repo.

## Connect (Claude Code)

**1. Get your connector URL — from your `know` admin.** Whoever stood up the brain has it
(it's on the onboarding card the installer prints). It looks like
`https://<brain-host>/mcp/<secret>/<your-name>/`, where `<brain-host>` is wherever your
team runs the brain. This URL **is** the credential — treat it like a password.

**2. Install the `know` plugin, scoped to the folder you want it in.** You get the
connector + the `/know:recall`, `/know:ingest`, `/know:contradictions`, `/know:resolve`, `/know:commit`
commands + an opt-out nudge to commit learnings. Use `--scope local` (this folder, just you) — **never** the default `user` scope,
which enables the brain in *every* folder you open:

```
cd /path/to/your/project
claude plugin marketplace add podclave/know --scope local
claude plugin install know@know --scope local --config mcp_url="<your-connector-url>"
claude plugin enable know@know --scope local
```

`--scope local` declares everything in `.claude/settings.local.json` (gitignored, just
you); your URL goes to Claude Code's **secure storage**, never to any settings file.
Installed in the wrong (`user`) scope already? Undo it with `claude plugin uninstall
know@know` + `claude plugin marketplace remove know`, then redo with `--scope local`.

**3. Verify and use it.** Run `claude` in that folder, then `/know:setup` (confirms the
connection) — or just ask *"what does the team know about X?"*. The first call may pause a
moment while an idle brain wakes. From then on Claude recalls when you ask about the
team/project and saves durable facts as they come up.

**Bringing in existing docs.** Starting from scattered PRDs, notes, and research? Run
`/know:ingest <files-or-folder>` — Claude reads the docs from here (local files, or
whatever your own connectors reach), extracts durable facts, and saves each with its
source. The secretary then dedupes, organizes, and cross-links them server-side; a large
load drains over a few minutes.

**Team repo:** use `--scope project` instead (or commit `.claude/settings.json`) so the
brain auto-enables **per-project** for everyone on clone + trust:

```json
{ "extraKnownMarketplaces": { "know": { "source": { "source": "github", "repo": "podclave/know" } } },
  "enabledPlugins": { "know@know": true },
  "permissions": { "allow": ["mcp__plugin_know_know__recall","mcp__plugin_know_know__list","mcp__plugin_know_know__contradictions"] } }
```

Reads auto-approve; `save`/`supersede`/`resolve` still prompt. Each teammate sets their own
URL once via the plugin config — only the non-secret settings are committed.

**Bare connector** (no `/know:` commands): `claude mcp add --transport http --scope local know "<your-connector-url>"`.

### claude.ai / Cowork — not recommended

The same URL works as a custom connector, but claude.ai connectors are **account-global**
(enabled in every conversation/project, not per-project) and need a manual Settings tweak
(Capabilities → Tool access mode) before tools load — and the model is likelier to reach
for a same-named local folder than the connector. There's no per-project scoping and no
plugin. Use Claude Code.

## Org-wide zero-setup provisioning (Podclave / managed settings)

Running an org? Instead of each teammate installing the plugin or pasting a URL, an admin
can provision **every** user at once with Claude Code **managed settings** — users do
nothing and `know` is just there on first launch. Drop the overlay's static files into a
**Podclave org bundle**.

The connector URL is fully env-driven, so the admin sets everything in **one place** —
`/etc/profile.d/know-identity.sh` — and the JSON files are copied verbatim:

1. **`/etc/profile.d/know-identity.sh`** — sets `KNOW_HOST` and `KNOW_SECRET` (your brain's, from the installer card) and bridges the per-user identity **file** `~/.podclave/user-email` into `KNOW_USER` (managed settings expand env vars, not files; missing → `anonymous`). `KNOW_HOST`/`KNOW_SECRET` carry no default — if unset the URL is plainly broken rather than silently wrong.
2. **`/etc/claude-code/managed-mcp.json`** — the connector, `https://${KNOW_HOST}/mcp/${KNOW_SECRET}/${KNOW_USER:-anonymous}/` (one shared file; no `managed-mcp.d/` exists — merge the `know` entry in if the file is already managed).
3. **`/etc/claude-code/managed-settings.d/50-know.json`** — a drop-in that auto-allows the six `know` tools (recall/save never prompt; the curation gate is the in-conversation approval) and arms the commit-nudge `UserPromptSubmit` hook. Drop-in files merge in lexical order and `permissions.allow` concatenates, so it coexists with other managed settings.
4. The nudge script ships at `client-plugin/nudge.py`; place a copy in the bundle at `etc/claude-code/know/nudge.py` (→ `/etc/claude-code/know/nudge.py`).

Ready-to-use templates (mirroring the deploy paths) live in [`examples/managed/`](examples/managed/),
and the installer's onboarding card prints your brain's `KNOW_HOST`/`KNOW_SECRET` values to
paste into `know-identity.sh`. This is an alternative to the per-user plugin / bare-connector
paths above, not a replacement. The `/know:*` slash commands are not provisioned this way
(they need the plugin); the nudge + natural language already drive recall/save/commit.

Two things to verify on a test box: that the `claude` session inherits the `profile.d`
env (else the URL falls back to `…/anonymous/` — set the vars wherever Podclave sources
session env), and the managed-file paths against your installed Claude Code version.

## Browse the brain (OKF visualizer)

Open `https://<brain-host>/viewer/<secret>/` in a browser for an interactive
graph of the curated knowledge base — nodes are concepts (colored by `type`), edges are
the cross-links; click a node to read the fact and follow its links. It's the OKF static
visualizer rendered on demand from the live bundle; same secret-in-path as the connector
(treat the URL like a password), no backend, nothing leaves the browser.

## Keeping it alive

A brain spins down when idle and auto-resumes on first connect. The one event the box
can't see while idle — an off-box edit pushed to the remote — is handled by the
**scheduled `wake.py` heartbeat**: run it hourly via Podclave Schedule (on Sprite) or a
plain crontab entry on a VM. A spun-down Sprite cannot run cron itself, so on Sprite the
heartbeat must be an off-box scheduler like a Podclave Schedule; a local crontab only
suits an always-on VM. It pulls the remote and reconciles any human edits. There
is no `/wake` HTTP endpoint; the heartbeat is a direct CLI command.

## Commit learnings (the nudge)

The `know` plugin ships a `UserPromptSubmit` nudge: when a session has built up durable
facts, it prompts Claude to propose them for your approval — nothing is saved without your
yes. Use `/know:commit` at any point to trigger this on demand. Tunables: set
`KNOW_NUDGE=0` to disable the automatic nudge, `KNOW_NUDGE_MIN_TURNS` to raise the
minimum turns before it fires (default 6), or `KNOW_NUDGE_GAP_TURNS` to widen the
cooldown between nudges (default 8). The nudge reuses the same `mcp_url` you set at
install — nothing extra to configure.

## Editing the brain directly (power users)

Clone the remote, edit any fact, commit, push. The secretary detects your edit by git
author and treats it as **authoritative** — it never clobbers a human edit, and a machine
fact that contradicts yours becomes an open record in `contradictions/` (recall flags it
as disputed; the observables report the open count). Editing the disputed fact **closes**
the record automatically. Reconcile happens on the next scheduled `wake` heartbeat.

## Security note — the secret is in the URL

The secret rides in the URL path, so under HTTPS it's encrypted in transit (only the
hostname is visible to a sniffer); the exposure is at-rest logs (the brain's own access
logs and Anthropic's connector storage). **Treat the URL like a password.** It's one
shared team secret with no per-user scoping; rotate by re-running the installer with a
new secret and re-issuing the connect card. Saves are scrubbed for common secret
patterns before they hit git, but don't put credentials in facts. Attribution is
self-asserted and unverified — fine for a trusted team, not an authentication boundary.

## Developing

See [docs/DEVELOPING.md](docs/DEVELOPING.md) for architecture, the safety model behind
the secretary, and the test suites (`cd server/gateway && .venv/bin/python -m pytest`).
