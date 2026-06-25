# know org-wide overlay (Podclave / Claude Code managed settings)

Provision every org user with the `know` connector + commit-nudge at **zero per-user
setup**. As the Podclave org admin, drop these static files into a **Podclave org bundle**.
Users do nothing — `claude` just has `know` on first launch.

Placing files in a bundle is a manual process. On the brain box (where you ran the
installer), run:

    bash examples/managed/output.sh

It prints every file the admin needs, each under a `# BUNDLE LOCATION: <path>` banner —
paste each block into the bundle at the path shown. It **auto-detects this brain's host +
secret** (secret from `~/.know/secret`, host from `sprite-env info` — where the installer
put them) and emits `.env.podclave.know` already filled in. Running off-box instead? Override
with `KNOW_HOST=… KNOW_SECRET=… bash examples/managed/output.sh`; with neither it prints the
`<brain-host>`/`<shared-secret>` placeholders to edit by hand. `KNOW_USER` is always filled
per-user automatically from the Podclave identity file, and the JSON files are emitted
verbatim (no per-deploy placeholders).

## Files

(Destinations, owner, and mode come from `output.sh`; these descriptions are just what
each file does. The three `/etc` files are owner `root`, mode `0644` — world-readable so
every user's `claude` can read them. `.env.podclave.know` is the box user's home dotfile,
owner `sprite`, mode `0644`.)

- `env.podclave.know` → placed at `.env.podclave.know`
  The one place env is set. **Podclave sources `.env.podclave.*` in every shell
  automatically** — this is the reliable bridge (`/etc/profile.d` is NOT sourced on
  Sprites). `KNOW_HOST` + `KNOW_SECRET` are admin-filled (no default — if unset the
  connector URL is plainly broken, which beats silently routing somewhere wrong).
  `KNOW_USER` is bridged from the per-user identity **file** `~/.podclave/user-email`
  (managed settings expand env vars, not files); missing file → `anonymous`.
  It carries the shared team secret — the same one each user's URL carries anyway, so no
  new exposure, but this overlay assumes **one brain per box**; do not use it to mix
  multiple teams' secrets on one box.

- `etc/claude-code/managed-mcp.json`
  The per-user connector: `https://${KNOW_HOST}/mcp/${KNOW_SECRET}/${KNOW_USER:-anonymous}/`.
  Copied verbatim. **There is no `managed-mcp.d/` drop-in** — if Podclave already manages
  this file, merge the `know` entry into the existing `mcpServers` object instead of
  overwriting it.

- `etc/claude-code/managed-settings.d/50-know.json`
  A **drop-in** settings file: auto-allows the six `know` tools (so recall/save never
  prompt — the curation gate is the in-conversation approval the model already requires)
  and arms the commit-nudge `UserPromptSubmit` hook. Drop-in files merge in lexical order,
  and `permissions.allow` **concatenates** with anything else managed, so this coexists
  with other managed settings rather than replacing them.

## Verify after deploy

On a test box: `claude doctor`, then launch `claude` and confirm the `know` tools are
present without a prompt. If the URL shows `…/anonymous/`, `.env.podclave.know` wasn't
sourced — confirm it's placed (Podclave sources `.env.podclave.*` automatically) and that
`~/.podclave/user-email` exists.
