# Team knowledge base — methodology

This repository **is** the team brain: one git repo of one-fact-per-file markdown.
This file is how it stays useful. It is read by the brain's recall agent, by the
secretary (the curator), and by any teammate who clones the repo. Editing this file
is how you evolve the methodology — it is pure convention, no code.

> Humans: edit any fact freely. The secretary detects human edits by git author and
> treats them as authoritative — it will never clobber your edit, and a machine fact
> that contradicts yours goes to `CONTRADICTIONS.md` for you to resolve, never over
> the top of your change.

## Config — the one pinned line

<!-- Resolved at install; re-pin = edit these two lines and re-run install-brain.sh -->
- model: claude-haiku-4-5-20251001
- claude-version: (recorded at install)

These pin the recall/secretary runtime. There is **no evergreen model alias** — dated
ids retire on Anthropic's clock, so this is a concrete id the install resolved and the
boot self-check verifies still resolves. Re-pin to a costlier model only as a deliberate
human call when recall is judged to be missing facts known to be present (never on a
metric).

## Layout

- `raw/` — append-only capture, one fact per file. Written by the `save` tool and
  passive capture. **Never edited in place.** Frontmatter: `id`, `title`, `author`,
  `surface`, `date`, optional `aliases`/`source`. This is the write path: cheap,
  always-accept.
- `curated/` — the polished, deduped, organized **read path**, owned by the secretary.
  Recall searches here first. Kept sharp so recall stays cheap and accurate.
- `INDEX` — a concise, scannable map of the curated set (titles + one-line gists,
  grouped by area). The secretary regenerates it each pass.
- `_superseded/` — retired facts. Nothing is ever deleted; superseding/promoting moves
  the old file here so history is preserved and every change is reversible.
- `CONTRADICTIONS.md` — the human-resolvable contradiction queue. The secretary never
  auto-picks a winner between conflicting facts; it files the conflict here.

## How a fact is written

- **One fact per file.** A fact is a single durable, specific, true-for-now statement:
  an infra/architecture detail (service, endpoint, owner, region, version, port), a
  decision, a convention, or a gotcha/known-issue.
- **Self-contained.** A reader with no other context should understand it. Prefer
  "The API gateway is Kong, owned by the platform team, on port 8000" over "We use
  Kong."
- **Title = the searchable claim.** Make the title the thing someone would search for.
- **Scope it.** When a brain spans multiple repos/areas (the default — a brain is per
  *concern*, not per repo), name the area in the title or body so "what's for what"
  stays clear (e.g. "Frontend (web-app repo): built with Next.js 14").
- **No secrets.** Tokens/keys/passwords never belong in a fact; they are scrubbed on
  write as a backstop, but don't rely on it.

## How the secretary curates (each pass)

1. **Promote** raw facts into curated facts: fold each raw fact into a well-titled
   curated fact, grouping related facts. Then the raw file moves to `_superseded/`.
2. **Dedupe**, including paraphrases — "Frontend is Next.js" and "the web-app uses
   Next.js 14" are the same fact; merge to the more specific one.
3. **Contradictions → the queue.** If a newer fact disagrees with an existing curated
   fact, file it in `CONTRADICTIONS.md` (both sides + the curated title). Do not
   overwrite. **Human always wins:** a human-edited curated fact is authoritative; a
   contradicting machine fact is queued, never applied over it.
4. **Regenerate `INDEX`.**
5. Never delete (move to `_superseded/`); stay within the blast-radius cap; keep every
   pass a single revertable `secretary:` commit.

## How recall works

Recall searches `curated/` + `INDEX` first, falling through to `raw/` on a miss, and
returns relevant content with an **honest confidence signal**: it says plainly when it
found nothing or only a partial match, and never presents a guess as an established
team fact. An empty or low-confidence result means "the brain may not know this," not
"the team has no such thing." When recall surfaces something the user clearly just
learned but the brain lacks, it may nudge them to `save` it.
