# Developing teamkb

The context to work **on** teamkb. To stand one up or use it, see
[../README.md](../README.md).

Status: working, verified end-to-end on a real public Sprite (install → connect over
the public URL → save → event-driven curation → recall; `/wake` heartbeat; idempotent
re-install).

## The pieces

All server code is `server/gateway/` (FastAPI, deployed to `~/teamkb-gateway` by the
installer). The KB data repo (`~/teamkb-kb` by default) is the truth.

- **`mcp_endpoint.py`** — the MCP-over-HTTP transport, mounted at the secret path
  `/mcp/<secret>/<name>/`. Lifted from podbrain's `build_router` (JSON-RPC /
  Streamable-HTTP: initialize/ping/tools/list/tools/call, notification→202, error
  codes, `isError` wrapping). Two changes: auth is `hmac.compare_digest` on the
  `<secret>` path segment (wrong secret → plain 404, never a 401/`WWW-Authenticate`
  that would trip OAuth), and the tools are recall/save/list/supersede dispatched to an
  injected `handlers` object (so the transport tests with a fake — no git, no claude).
- **`store.py`** — the git-markdown store. `save`/`list`/`supersede`, scrub-on-write,
  commits via the **env-pinned identity wrapper** (`-c user.email=…` per invocation,
  never a clonable gitconfig). `supersede` moves to `_superseded/` (never `rm`).
- **`recall.py`** — `recall(query)` spawns a cheap `claude -p` with read-only file
  tools (`Read`/`Grep`/`Glob`) in the repo; the `curated/` OKF bundle first, raw/ on a miss. The
  §5.5 observables (empty-brain honesty, curated-K-vs-raw-M count, loud auth-invalid
  message) are computed **deterministically in Python**, not left to the model.
- **`secretary.py`** — the curator (see safety model below).
- **`config.py`** — the two reserved bot identities, paths, model-pin resolution,
  `claude_bin()`.
- **`boot_check.py`** — the auth probe, version-floor check, model-resolves check, and
  cheapest-haiku resolver. Used by the installer's ordered self-check and by `/wake`.
- **`app.py`** — wires it together; the event-driven secretary trigger and `/wake`.
- **`server/kb-template/CLAUDE.md`** — the methodology seeded into each KB repo. **This
  is the real product surface** — curation quality rides on it, and it's pure
  convention (no code), so it stays editable forever.

## The secretary's safety model (the important part)

A cheap model curates; **deterministic Python enforces every safety invariant around
it.** That split is the whole design — a weak model's judgment must never be able to
clobber a human edit, delete a fact, or run away across the repo.

- The **agent** (judgment) may write ONLY to `curated/` and `CONTRADICTIONS.md`; it has
  no Bash, so it can't `rm` or `git`. It reports a manifest of which raw ids it
  incorporated/queued.
- **Python** (safety), after the agent runs, regardless of what the agent did:
  - **never rm** — `enforce_whitelist()` reverts any agent change outside that
    write-whitelist (incl. anything it touched under `raw/`/`_superseded/`); the only
    raw mutation is Python's own `git mv` of incorporated/queued facts to
    `_superseded/`.
  - **human always wins** — files touched by unreconciled HUMAN commits (author email
    ≠ the two reserved bot identities) are in `protected`; the agent is told to skip
    them and Python reverts them if it doesn't. A contradicting machine fact goes to
    `CONTRADICTIONS.md`, never over the human (spec §13.4).
  - **blast-radius cap** — past N changed files the pass bails with a review note.
  - **optimistic concurrency** — if a human commit lands mid-pass (HEAD moved off the
    start ref R with a non-bot author), abort and defer to the next pass.
  - **single-flight** — an flock so two passes never race.
  - **revertable** — every pass is one distinct `secretary:`-tagged commit; a local
    `refs/secretary/base` marks the last reconciled HEAD.

`test_secretary.py` proves each invariant with a **fake agent** (scripted file actions,
no model). Quality — does it organize a messy repo well — is verified live, separately
(it does: merges paraphrase dupes, queues contradictions, protects human facts,
idempotent on a second pass).

## OKF — `curated/` is an Open Knowledge Format bundle

[OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
is Google's vendor-neutral spec for the "LLM-wiki" pattern — markdown concept docs with
YAML frontmatter, an `index.md`, and cross-links. teamkb was ~90% this shape already;
conforming costs nothing and means the curated bundle is readable by any OKF tool (e.g.
the OKF static graph visualizer) with zero lock-in and no GCP dependency.

Mapping: **`curated/` is the bundle** (flat); `raw/`, `_superseded/`, `CLAUDE.md`,
`CONTRADICTIONS.md` are teamkb-internal, outside it. Each concept doc carries
`type` (OKF's one required field) / `title` / `description` / `tags` / `timestamp` plus
teamkb extension keys (`author`/`surface`/`source`/`id`, which OKF preserves). Frontmatter
is real YAML (`pyyaml`) since other tools parse it.

Same split as the safety model — **the agent authors judgment, Python guarantees the
invariant:**
- The agent writes conformant concept docs and **cross-links** them, following Google's
  own enrichment-agent rules (from their `enrichment_instruction.md`): link in prose when
  naturally referencing another concept; file-relative paths only (never start with `/`);
  only link concepts that exist; one link per mention; no links in headings/code/self.
- Python (`secretary.py`) then **guarantees conformance regardless of the model**:
  `backfill_types()` sets a default `type` on any concept missing one; `generate_index()`
  deterministically rebuilds `curated/index.md` (grouped by `type`, with `okf_version`);
  `validate_links()` checks every intra-bundle link resolves and reports broken/absolute
  ones in the pass observables (OKF tolerates broken links, so this reports, not fails).

Verified live: a real curation pass over 5 relatable facts produced 5 conformant concepts
with 9 resolving cross-links, 0 broken; idempotent on re-run.

## Lessons carried over from podbrain (pre-empted, not rediscovered)

- **A down brain must be a VISIBLE tool error**, never silent success. The MCP layer
  wraps any handler exception as an `isError` tool result the model sees ("teamkb call
  failed: …"). Recall raises a distinct, loud message on auth failure vs a generic
  agent failure.
- **`claude -p` writes its own transcript** → the passive-capture plugin skips
  transcripts containing the `DISTILLER_MARKER`, and the recall/secretary agents set a
  `TEAMKB_AGENT` recursion guard so nested hooks bail.
- **Feedback loop** → the capture plugin strips injected `<team-brain-context>` blocks
  and `isMeta` entries before distilling, so the brain never re-ingests what it recalled.
- **Scope the API key to the service, not the shell** (spec §9.8) — a global
  `ANTHROPIC_API_KEY` overrides the box owner's interactive subscription and the
  approval sticks in `~/.claude/.credentials.json`. The installer sets it only on the
  `sprite-env` service env.
- **Pin the model + record the claude version** — `claude update` pulls unpinned latest,
  so without recording, brain #1 and #N run un-bisectable runtimes. Both live on one
  line in the KB repo's CLAUDE.md; the boot self-check verifies the model still resolves
  and fails loud on deprecation.
- **`claude` is a node app under a minimal service PATH** → `config.claude_bin()`
  resolves it and the installer passes `PATH` into the service env.

## Known limitations (deliberate)

- **Cheap-tier recall has a quality ceiling** as `raw/` grows. The fix is a **manual**
  re-pin to a costlier model (edit the CLAUDE.md model line + re-run install) — never a
  metric-driven auto-bump (a "miss" usually just means the brain doesn't have that
  fact; recall says so honestly). The §7 canonical-seed-set hit/miss is informational
  only and not wired as a trigger.
- **Capture is uniform-by-reliance, not in-practice** — only model-initiated capture is
  load-bearing; the CC plugin nudges it but web/cowork have no hook, so a cowork-heavy
  team builds a thinner brain unless a power user feeds it.
- **Reconcile latency = one heartbeat interval** — an off-box mirror push isn't seen
  until the next `/wake`. The immediate fix (a GitHub webhook → `/wake`) is intentionally
  deferred; hard-skip + optimistic concurrency already remove clobber risk.
- **Attribution is self-asserted**, the secret is shared, and the bot/human classifier
  is forgery-resistant not -proof — all fine for a trusted team, all out of the threat
  model. Commit signing is harden-later.

## Tests

```bash
cd server/gateway && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest          # 37 tests: transport, store, secretary invariants
```

Transport + store + secretary-safety run with no claude and no network. Recall and
secretary *quality* are checked by pointing a real key at a fixture repo (see the
commit history for the live-verification commands).
