# know org-wide overlay (Podclave / Claude Code managed settings)

Provision every org user with the `know` connector + commit-nudge at **zero per-user
setup**. As the Podclave org admin, drop these static files into a **Podclave org bundle**.
Users do nothing — `claude` just has `know` on first launch.

Placing files in a bundle is a manual process. Run:

    bash examples/managed/output.sh

It prints every file the admin needs, each under a `# BUNDLE LOCATION: <path>` banner —
copy each block into the bundle at the path shown. The files below are the source of those
blocks (and `client-plugin/nudge.py`).

## What the admin edits

**Only one file**, `etc/profile.d/know-identity.sh`. Set your brain's host and shared
secret there (the installer's onboarding card prints both values):

    export KNOW_HOST="your-brain.example.com"   # host only, no scheme
    export KNOW_SECRET="<the shared team secret>"

`KNOW_USER` is filled automatically from the Podclave identity file. The JSON files below
are copied **verbatim** — they read those env vars, so there are no per-deploy
placeholders to hand-edit.

## Files

(Destinations come from `output.sh`; these descriptions are just what each file does.)

- `etc/profile.d/know-identity.sh`
  The one place env is set. `KNOW_HOST` + `KNOW_SECRET` are admin-filled (no default — if
  unset the connector URL is plainly broken, which beats silently routing somewhere
  wrong). `KNOW_USER` is bridged from the per-user identity **file** `~/.podclave/user-email`
  (managed settings expand env vars, not files); missing file → `anonymous`.
  The secret lands in a world-readable `/etc` file — the same shared team secret each
  user's URL carries anyway, so it is no new exposure, but this overlay assumes **one
  brain per box**; do not use it to mix multiple teams' secrets on one box.

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
present without a prompt. If the URL shows `…/anonymous/`, the session didn't inherit the
`profile.d` env — set the vars wherever Podclave sources session environment.
