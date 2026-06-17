# Team knowledge base — methodology

This repository **is** the team brain: one git repo of one-fact-per-file markdown.
This file is how it stays useful. It is read by the brain's recall agent, by the
secretary (the curator), and by any teammate who clones the repo. Editing this file
is how you evolve the methodology — it is pure convention, no code.

The `curated/` directory is an **[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
(OKF) bundle** — a portable, vendor-neutral standard for AI-agent knowledge that is
"just markdown, just files, just YAML frontmatter." Conforming costs us nothing (we
were already this shape) and means the curated brain can be read by any OKF tool — e.g.
rendered as an interactive graph by the OKF static visualizer — with zero lock-in.

> Humans: edit any fact freely. The secretary detects human edits by git author and
> treats them as authoritative — it will never clobber your edit, and a machine fact
> that contradicts yours becomes an open record in `contradictions/` for you to resolve,
> never applied over the top of your change. Editing the disputed fact closes the record.

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
  passive capture. **Never edited in place.** This is the write path: cheap, always-accept.
  (Staging, not part of the published OKF bundle.)
- `curated/` — **the OKF bundle**: the polished, deduped, organized **read path**, owned
  by the secretary. Recall searches here first. Each `curated/<slug>.md` is an OKF concept
  document; `curated/index.md` is the bundle index (regenerated automatically).
- `_superseded/` — retired facts. Nothing is ever deleted; superseding/promoting moves
  the old file here so history is preserved and every change is reversible.
- `contradictions/` — the human-resolvable contradiction queue: one structured record
  (`status`/`target`/sides) per OPEN conflict. The secretary never auto-picks a winner;
  it files a record and recall flags it. Resolved records move to `contradictions/resolved/`.

## How a fact (OKF concept document) is written

Every `curated/<slug>.md` is YAML frontmatter then a markdown body:

```
---
type: Decision            # REQUIRED — Fact | Decision | Convention | Gotcha | Runbook | Architecture | Reference
title: Primary database is PostgreSQL 16
description: The team standardized on PostgreSQL 16 for all services.
tags: [database, postgres]
timestamp: '2026-06-17T04:00:00Z'
---
The team standardized on PostgreSQL 16 for all services, decided in the Q2 review.
```

- **One fact per file.** A single durable, specific, true-for-now statement.
- **Self-contained.** A reader with no other context should understand it. Prefer "The
  API gateway is Kong, owned by the platform team, on port 8000" over "We use Kong."
- **`type` is required** (OKF's one hard rule); `title`/`description`/`tags`/`timestamp`
  are recommended. `description` is a one-line summary used in previews and the index.
- **Scope it.** A brain is per *concern*, not per repo — name the area in the title/body
  so "what's for what" stays clear (e.g. "Frontend (web-app): built with Next.js 14").
- **No secrets.** Tokens/keys/passwords never belong in a fact; scrubbed on write as a
  backstop, but don't rely on it.

## Cross-linking (the knowledge graph)

Curated concepts link to each other with plain markdown links, forming an OKF knowledge
graph. Follow these rules (they keep the graph honest and the noise low):

- Link when a concept's prose **naturally references another concept by name** —
  `[Deploy pipeline](deploy-pipeline.md)`. The relationship is conveyed by the prose.
- **File-relative paths only.** Never start a link with `/` (breaks GitHub rendering);
  curated/ is flat, so links are bare sibling filenames.
- **Only link concepts that actually exist.** Never invent a link target.
- **One link per concept mention per section** — do not over-link. No links in headings,
  code blocks, or frontmatter; never link a document to itself.

## How the secretary curates (each pass)

1. **Promote** raw facts into curated OKF concept documents (well-titled, correct `type`,
   a one-line `description`), grouping related facts. Then the raw file moves to `_superseded/`.
2. **Dedupe**, including paraphrases — "Frontend is Next.js" and "the web-app uses
   Next.js 14" are the same fact; merge to the more specific one.
3. **Cross-link** related concepts per the rules above.
4. **Contradictions → the queue.** If a newer fact disagrees with an existing curated
   fact, file a structured record in `contradictions/<slug>.md` (`status: open`,
   `target:` the disputed concept, both sides) — first check for an existing open record
   on that target so you don't duplicate. Do not overwrite the curated fact. **Human
   always wins:** a human-edited curated fact is authoritative; a contradicting machine
   fact is queued, never applied over it. When a human edits a disputed concept, the
   record is closed automatically (moved to `contradictions/resolved/`).
5. Never delete (move to `_superseded/`); stay within the blast-radius cap; keep every
   pass a single revertable `secretary:` commit. (`curated/index.md`, a missing `type`,
   and contradiction resolution are handled automatically — you don't hand-maintain them.)

## How recall works

Recall searches `curated/` + `curated/index.md` first, falling through to `raw/` on a
miss, and returns relevant content with an **honest confidence signal**: it says plainly
when it found nothing or only a partial match, and never presents a guess as an
established team fact. An empty or low-confidence result means "the brain may not know
this," not "the team has no such thing." When recall surfaces something the user clearly
just learned but the brain lacks, it may nudge them to `save` it. If an OPEN record in
`contradictions/` covers what's being asked, recall warns prominently that the fact is
disputed rather than giving a confident single answer.
