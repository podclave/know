# /etc/profile.d/know-identity.sh
# Expose the Podclave per-user identity (the file ~/.podclave/user-email) as $KNOW_USER,
# so /etc/claude-code/managed-mcp.json can expand it into each user's connector URL.
# Missing file -> "anonymous" (a valid, generic URL) rather than a broken one.
export KNOW_USER="$(cat "$HOME/.podclave/user-email" 2>/dev/null || echo anonymous)"
