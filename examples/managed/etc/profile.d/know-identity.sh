# /etc/profile.d/know-identity.sh
# The ONE place the admin sets the know overlay's environment. managed-mcp.json expands
# these into each user's connector URL: https://${KNOW_HOST}/mcp/${KNOW_SECRET}/${KNOW_USER}/
#
# Admin: fill in your brain's host + shared secret (from the installer's onboarding card).
# Leave no default on these two — if unset the connector URL is plainly broken (visible),
# which beats silently routing somewhere wrong.
export KNOW_HOST="<brain-host>"        # host only, no scheme, e.g. your-brain.example.com
export KNOW_SECRET="<shared-secret>"   # the shared team secret from the connect card
#
# Per-user attribution from the Podclave identity file. Missing file -> "anonymous"
# (a valid, generic URL) rather than a broken one.
export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"
