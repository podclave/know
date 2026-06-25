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
  (the installer's onboarding card prints this file already filled in). This overlay assumes
  every user on the box shares one brain (one team secret); the secret lands in a world-readable
  `/etc` file — the same shared team secret each user's URL carries anyway, so it is no new
  exposure, but do not use this overlay to mix multiple teams' secrets on one box. **There is no
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
