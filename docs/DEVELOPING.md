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
- **`agent.py`** — server-side agent invocation via the **Claude Agent SDK**
  (`claude-agent-sdk`). `collect()` (async, for recall) / `run_sync()` (for the secretary
  in a worker thread) run the SDK's bundled native CLI with `allowed_tools`, `cwd`,
  `setting_sources=None` (isolated from the box's `~/.claude`), and structured output;
  both return an `AgentResult` carrying text/structured/cost/tokens. Replaces shelling out
  to `claude -p`.
- **`recall.py`** — `recall(query)` runs a cheap read-only agent (`Read`/`Grep`/`Glob`)
  over the repo; the `curated/` OKF bundle first, raw/ on a miss. The §5.5 observables
  (empty-brain honesty, curated-K-vs-raw-M count, loud auth-invalid message) are computed
  **deterministically in Python**, not left to the model.
- **`secretary.py`** — the curator (see safety model below).
- **`config.py`** — the two reserved bot identities, paths, model-pin resolution, the
  agent recursion-guard env.
- **`boot_check.py`** — the auth probe, agent-runtime version check (the SDK's *bundled*
  CLI version), model-resolves check, and cheapest-haiku resolver. Used by the installer's
  ordered self-check and by `/wake`.
- **`app.py`** — wires it together; the event-driven secretary trigger and `/wake`.
- **`server/kb-template/CLAUDE.md`** — the methodology seeded into each KB repo. **This
  is the real product surface** — curation quality rides on it, and it's pure
  convention (no code), so it stays editable forever.

## The secretary's safety model (the important part)

A cheap model curates; **deterministic Python enforces every safety invariant around
it.** That split is the whole design — a weak model's judgment must never be able to
clobber a human edit, delete a fact, or run away across the repo.

- The **agent** (judgment) may write ONLY to `curated/` and `contradictions/`; it has
  no Bash, so it can't `rm` or `git`. It runs via the Agent SDK with a forced
  `output_format` JSON schema, so it reports a **schema-validated manifest** (which raw
  ids it incorporated/queued/deferred) in `ResultMessage.structured_output` — mapped by
  `_result_to_manifest()`, no regex-salvage. The same result carries `total_cost_usd` +
  token `usage`, which land in the per-pass observables note (`[cost] pass_usd=…
  tokens_in/out=…`) and the `run_pass` result.
- **Python** (safety), after the agent runs, regardless of what the agent did:
  - **never rm** — `enforce_whitelist()` reverts any agent change outside that
    write-whitelist (incl. anything it touched under `raw/`/`_superseded/`); the only
    raw mutation is Python's own `git mv` of incorporated/queued facts to `_superseded/`.
  - **a fact leaves `raw/` only when it's verifiably represented** — `_represented()`
    checks the raw fact's title tokens against the curated bundle (incorporated) or
    `contradictions/` (queued) using a FRESH `raw/` snapshot taken after the agent runs.
    Content-based, so it blocks a lying/empty manifest from moving uncurated facts AND
    self-heals facts already represented (a re-run, or a `save` that lands mid-pass as a
    `capture` commit) instead of leaving them duplicated in `raw/` + `curated/`.
  - **human always wins** — files touched by unreconciled HUMAN commits (author email
    ≠ the two reserved bot identities) are in `protected`; the agent is told to skip them
    and Python reverts them if it doesn't. A contradicting machine fact goes to a
    structured `contradictions/<slug>.md` record, never over the human (spec §13.4).
  - **contradiction dequeue** — `resolve_contradictions()`: when a human edits a curated
    concept that a PRE-EXISTING open contradiction targets, the human has spoken, so the
    record is closed (moved to `contradictions/resolved/`, never rm). A record filed in
    the same pass isn't auto-closed (a pass-start snapshot gates this). Recall flags any
    open record on the queried concept; `/wake` + the observables report the open count.
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
`contradictions/` are teamkb-internal, outside it. Each concept doc carries
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
- **Agents run via the Claude Agent SDK, not `claude -p`** → the SDK bundles a pinned,
  native (Node-free) CLI in the venv, so the agent runtime is self-contained,
  version-reproducible across installs (the SDK version IS the pin — no `claude update`,
  no record-the-resolved-version dance), and isolated from the box owner's interactive
  `claude` (`setting_sources=None` + the bundled binary, so no user hooks/settings load).
  This is what makes standing a brain up on any host a `pip install`. The recursion-guard
  env (`TEAMKB_AGENT`) is still set, belt-and-suspenders.
- **Feedback loop** → the capture plugin strips injected `<team-brain-context>` blocks
  and `isMeta` entries before distilling, so the brain never re-ingests what it recalled.
  (The plugin runs on the teammate's own machine and still uses their `claude -p`.)
- **Scope the API key to the service, not the shell** (spec §9.8) — a global
  `ANTHROPIC_API_KEY` overrides the box owner's interactive subscription and the
  approval sticks in `~/.claude/.credentials.json`. The installer sets it only on the
  `sprite-env` service env; the SDK reads it from there.
- **Pin the model + record the runtime** — the model id lives on one line in the KB
  repo's CLAUDE.md (boot self-check verifies it still resolves, fails loud on
  deprecation); the agent runtime is pinned by the `claude-agent-sdk` version and its
  bundled CLI version is recorded alongside, so brain #1 and #N run identical runtimes.

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
.venv/bin/python -m pytest          # transport, store, secretary invariants, OKF, viewer
```

Transport + store + secretary-safety + viewer run with no agent calls and no network
(the agent is injected as a fake). Recall and secretary *quality* are checked by pointing
a real key at a fixture repo (see the
commit history for the live-verification commands).
