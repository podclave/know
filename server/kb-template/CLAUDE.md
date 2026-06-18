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
> never applied over the top of your change.
>
> You resolve a dispute one of two ways, and both close the record (moved to
> `contradictions/resolved/`, never deleted): **(a) right in a Claude conversation** —
> ask "what's contested?" (the `contradictions` tool) and decide with the `resolve` tool
> (`keep` the curated fact, or `replace` it with a correction); the decision is attributed
> to you. Or **(b) edit the disputed curated fact yourself** (power-user / git path).
> A conversational `resolve` commits under your name, so it rides the same "human always
> wins" protection a hand-edit does.

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
  `source` is optional provenance — where a fact came from (a doc, an ADR, a decision) —
  worth setting when you ingest external material.
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

## Working in the repo directly (power user)

Clone the repo and curate it in a Claude Code session instead of going through `save` —
the right move when you're folding in external material (PRDs, ADRs, research, notes on
the same machine). **Your session is the smart one here.** The on-box secretary is a cheap
model running janitorial passes; when you work directly, the heavy lifting — reading the
sources, deciding what's durable, structuring and connecting it — is yours. Do it well;
don't write sloppy facts and count on the box to fix them.

Folding a pile of docs into the bundle:

- **Read it all, then extract.** Pull out durable, atomic facts — one per
  `curated/<slug>.md`, in the format above. Skip the ephemeral. Split a doc into several
  facts; merge several docs into one fact where they say the same thing.
- **Dedupe against what's here first.** Read `curated/` before you write — fold new
  knowledge into an existing concept rather than adding a near-duplicate.
- **Write straight to `curated/`** (you're curating; `raw/` is the always-accept capture
  path for the `save` tool). Set `type`, a one-line `description`, and `source`.
- **Cross-link as you go** (rules above). The box won't add links *into* your files on the
  pass right after you push — they're yours, protected — so the graph is only as connected
  as you make it.
- **Keep the source docs out of the repo.** Gitignore or delete your scratch folder; only
  the extracted facts belong in the bundle.
- **Commit as yourself — never as `secretary:`.** Human authorship is exactly what makes
  your work authoritative; the box never clobbers a human-authored fact.

`curated/index.md`, `type` backfill, and link validation are regenerated **on the box** on
the next pass after you push (via `/wake`) — there's no curator in your clone. Leave the
index alone, or regenerate it for a correct local view; the box is authoritative.

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
5. Never delete (move to `_superseded/`); keep every
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
