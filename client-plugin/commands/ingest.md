---
description: Ingest existing docs (PRDs, notes, research) into the team know brain
argument-hint: [files, globs, or a folder — or describe where the docs are]
---
Bring existing team material into the **know** brain: $ARGUMENTS

The know brain stores **one durable fact per entry** and a server-side secretary then
dedupes, organizes, and cross-links them — so your job here is to turn documents into
atomic facts and `save` them. The brain never reads the docs itself; you do, from here.

**1. Gather the source material.** Use whatever's referenced in $ARGUMENTS — local files,
globs, or a folder. If it lives in Google Drive / Notion / elsewhere, use your own
connectors or ask me to export it locally first; the know connector has no access to it.
If $ARGUMENTS is empty, ask me what to ingest.

**2. Extract durable facts.** Read each source and pull out statements that are **durable,
specific, and true-for-now** — decisions, conventions, architecture, gotchas, runbooks,
key references. Each fact must be **self-contained** (a reader with no other context
understands it) and **one fact per `save`**. Skip the ephemeral: status updates, meeting
chatter, anything that'll be stale next week. **Never save secrets** (tokens, keys,
passwords) even if they're in the doc.

**3. Show me the plan before saving.** List the facts you intend to save (title + type +
which source each came from) and roughly how many. Wait for my go-ahead — don't bulk-save
blind. For a large pile, a quick `recall` on the main topics first helps you avoid
re-saving things the brain already knows.

**4. Save each fact** with the `save` tool:
- `title` — a precise, self-contained statement (e.g. "Primary database is PostgreSQL 16").
- `body` — the fact in full, enough to stand alone.
- `type` — one of `Fact`, `Decision`, `Convention`, `Gotcha`, `Runbook`, `Architecture`,
  `Reference` (the secretary refines this if you're unsure).
- `tags` — a few topic tags.
- `source` — **where it came from** (the doc name/path, e.g. `roadmap-q3.md`), so the fact
  is traceable back to its origin. Always set this on ingest.

**5. Hand off to the secretary.** Once saved, tell me it's in — the secretary curates,
dedupes against existing knowledge, files any contradictions, and cross-links it
automatically (a large load drains over a few minutes, no action needed). Anyone can then
`recall` it. Don't try to organize `curated/` yourself — that's the brain's job.
