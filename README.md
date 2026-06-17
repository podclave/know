# know

A small, self-hosted **team brain**: one server per team/concern that gives every
teammate's Claude shared, durable memory. Ask a question and **recall** returns what
the team has learned; learn something durable and your Claude **saves** it. A
server-side **secretary** keeps the knowledge organized. The whole thing is a git repo
of one-fact-per-file markdown — the git repo is the truth — wrapped in an
MCP-over-HTTP server you connect to as a single URL.

**Claude Code is the home surface:** install the `know` plugin (one step — the MCP
connector + `/know:` commands + optional passive capture) and point it at your personal
URL. claude.ai / Desktop / Cowork can connect to the same URL, but there a connector is
account-global and needs manual settings — prefer Claude Code (see Connect below).

> Standalone and open-source-able (its own repo). Inspired by — and lifting ~⅔ of its
> server scaffolding from — [podbrain](https://github.com/podclave/podbrain), but with
> a different engine: no vector DB, just git + markdown + a cheap `claude` agent.

## How it works

```
   external pinger (hourly) ──poke──▶  <brain>/wake   (auth probe · pull mirror · reconcile · liveness)
                                          │
   ┌──────────────────────────────────────▼─────────────────────────────┐
   │  BRAIN — one Sprite, a supervised FastAPI MCP-over-HTTP service       │
   │   • git repo of markdown facts = the truth  → optional private mirror │
   │   • recall   — a cheap `claude` agent greps/reads the repo            │
   │   • save/list/supersede — write tools, scrubbed + committed to git     │
   │   • secretary — a `claude` that promotes raw→curated, dedupes, queues  │
   │                 contradictions, regenerates INDEX (human edits win)    │
   └──────────────────────────────┬───────────────────────────────────────┘
                MCP over HTTP, no auth header — a SECRET in the URL PATH:
                       https://<brain>.sprites.app/mcp/<secret>/<name>/
        ┌────────────────────┬──────────────┴───────┬─────────────────────┐
   Claude Code          claude.ai              Desktop                 Cowork
   (add the URL)        (add the URL)          (add the URL)           (add the URL)
```

- **Auth = a secret in the URL path** (the capability-URL pattern, like a Slack
  webhook). MCP auth is optional and every connector surface accepts a no-auth URL —
  no bearer header (the web UIs have no field for one), no OAuth subsystem to age out.
  The `<name>` segment is self-asserted attribution stamped on saves.
- **The brain authenticates to Anthropic with an API key** (static — no login that
  expires on a clock), scoped to the service only, never your interactive `claude`.
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

On a **public** Sprite (or any host — see below) with an `ANTHROPIC_API_KEY` available
(default: the `sk-` line of `~/ANTHROPIC_API_KEY`):

```bash
bash server/install-brain.sh [brain-name]
```

Idempotent — safe to re-run; standing up brain #N is the same command on a fresh host.
No Node or system `claude` needed: the agent runtime is the **Claude Agent SDK's bundled
native CLI**, installed into the gateway venv by `pip` — self-contained, version-pinned
by the SDK, and isolated from any interactive `claude` on the box. The installer pins the
cheapest dated model id + records the bundled CLI version, mints the secret, inits the git
repo (and a private `gh` mirror unless `BRAIN_NO_MIRROR=1`), creates the supervised service
with the API key scoped to it, runs an **ordered boot self-check** (auth → agent runtime →
model-resolves — refuses to report green on any failure), smoke-tests a real save+recall,
and prints an onboarding card with your connect URL and the `/wake` heartbeat URL.

Because the runtime is just a `pip install` (no Node, no global CLI, no `claude update`),
the same script stands a brain up on a plain VM — e.g. a DigitalOcean droplet — not only a
Sprite. (The `sprite-env` service wrapper is the one Sprite-specific piece; on another host
run the gateway under any supervisor.)

Useful env: `BRAIN_GITHUB_MIRROR=owner/repo`, `BRAIN_NO_MIRROR=1`,
`BRAIN_ALERT_WEBHOOK=<slack-webhook>` (auth-failure alerts), `CLAUDE_FLOOR=2.1.92`.

## Connect (Claude Code)

Each teammate has a personal URL `https://<brain>.sprites.app/mcp/<secret>/<your-name>/`
— the `<name>` is your attribution, and the URL **is** the credential (treat it like a
password).

**Recommended — the `know` plugin** (one install: the connector + `/know:recall`,
`/know:contradictions`, `/know:resolve` commands + optional capture). Install it **scoped
to the folder you want it in** — never the default `user` scope, which would enable the
brain in *every* folder you open:

```
cd /path/to/your/project
claude plugin marketplace add podclave/know --scope local
claude plugin install know@know --scope local --config brain_mcp_url="https://<brain>.sprites.app/mcp/<secret>/<your-name>/"
claude plugin enable know@know --scope local
```

`--scope local` declares everything in `.claude/settings.local.json` (this folder, just
you — gitignored); your URL goes to Claude Code's **secure storage**, never to any settings
file. Already installed in the wrong (`user`) scope? Undo it with
`claude plugin uninstall know@know` + `claude plugin marketplace remove know`, then redo
with `--scope local`.

For a **team** repo, use `--scope project` instead (or commit `.claude/settings.json`) so
the brain auto-enables **per-project** for everyone on clone + trust:

```json
{ "extraKnownMarketplaces": { "know": { "source": { "source": "github", "repo": "podclave/know" } } },
  "enabledPlugins": { "know@know": true },
  "permissions": { "allow": ["mcp__plugin_know_know__recall","mcp__plugin_know_know__list","mcp__plugin_know_know__contradictions"] } }
```

Reads auto-approve; `save`/`supersede`/`resolve` still prompt. Each teammate sets their own
URL once via the plugin config — only the non-secret settings are committed.

**Bare connector** (no `/know:` commands or capture): `claude mcp add --transport http --scope local know "<your-url>"`.

Then just use Claude normally: it recalls when you ask about the team/project and saves
durable facts as they come up. You never see a repo, sync, or file.

### claude.ai / Cowork — not recommended

The same URL works as a custom connector, but claude.ai connectors are **account-global**
(enabled in every conversation/project, not per-project) and need a manual Settings tweak
(Capabilities → Tool access mode) before tools load — and the model is likelier to reach
for a same-named local folder than the connector. There's no per-project scoping and no
plugin. Use Claude Code; reach for the web surfaces only if you must.

## Browse the brain (OKF visualizer)

Open `https://<brain>.sprites.app/viewer/<secret>/` in a browser for an interactive
graph of the curated knowledge base — nodes are concepts (colored by `type`), edges are
the cross-links; click a node to read the fact and follow its links. It's the OKF static
visualizer rendered on demand from the live bundle; same secret-in-path as the connector
(treat the URL like a password), no backend, nothing leaves the browser.

## Keeping it alive

A brain spins down when idle and auto-resumes on first connect. Normal capture wakes
the box and triggers curation. The one event the box can't see — an off-box edit pushed
to the mirror — rides an **external pinger** (Podclave Schedule, GitHub Actions cron, or
any uptime monitor) that POSTs to `<brain>/wake` hourly: it runs the auth probe (and
alerts on failure), pulls the mirror, reconciles human edits, and reports curator
liveness. A spun-down box can't cron itself, so this pinger is required.

## Passive capture (part of the plugin)

The `know` plugin also ships an optional Stop/SessionEnd hook that distills durable facts
from each Claude Code session and saves them — a CLI-only nicety the design does **not**
rely on (model-initiated `save` already works without it; web surfaces have no hook). It
reuses the same `brain_mcp_url` you set at install, so there's nothing extra to configure.

## Editing the brain directly (power users)

Clone the mirror, edit any fact, commit, push. The secretary detects your edit by git
author and treats it as **authoritative** — it never clobbers a human edit, and a machine
fact that contradicts yours becomes an open record in `contradictions/` (recall flags it
as disputed; `/wake` reports the open count). Editing the disputed fact **closes** the
record automatically. Reconcile happens on the next `/wake` (≈ one heartbeat interval).

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
