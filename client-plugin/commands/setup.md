---
description: Check this machine's connection to the team know brain
---
Verify this machine's connection to the team **know** brain:

1. Call the `list` tool on the know connector. If it returns facts (or an empty-brain message), the connector is working — tell me it's connected.
2. If it errors or the tool isn't available, the plugin's **Brain connector URL** isn't set. Tell me to configure it via the know plugin's settings: it's the full `https://<brain-host>/mcp/<secret>/<my-name>/` URL (the URL is the credential — treat it like a password).

Then briefly remind me of what's available: the tools `recall`, `save`, `list`, `supersede`, `contradictions`, `resolve`, `viewer` (returns the brain's browser graph URL), and the `/know:recall`, `/know:commit`, `/know:ingest`, `/know:contradictions`, `/know:resolve` commands. Note that I save durable facts only after you approve them (the model proposes, I pick) — and that it will occasionally nudge me to commit learnings when a session has built some up.
