# know — Simplification & User-Curated Learning (Design)

**Date:** 2026-06-25
**Status:** Approved for planning
**Scope:** Client plugin + server trim (not a full architecture rethink)

## Problem

`know` works, but two things cut against how it should feel:

1. **The save path is too autonomous.** The `save` tool description tells the model
   to "Call this WITHOUT being asked," and the client `capture.py` Stop/SessionEnd
   hook auto-distills and auto-saves every session in the background with no curation
   gate. This is the residue of earlier, over-prescriptive experiments (hooks that
   *force* storage). The user should curate what goes into the team brain.

2. **Standing a brain up is a credential-provisioning ceremony.** The installer
   requires an `ANTHROPIC_API_KEY`, manages a key file, bakes the key into the service
   env, and runs a hard REST auth gate that refuses to come up green without it.
   Plus an external HTTP pinger must be wired to `/wake` to reconcile off-box edits.

Recall, by contrast, is already where it should be: the model recalls when relevant
and reads auto-approve.

## Guiding Principles

1. **Recall stays frictionless** — unchanged.
2. **Every save is user-curated** — the model *proposes*, the user *approves*, then it
   saves. Nothing reaches the brain on the model's own initiative.
3. **Nudges are complementary, never forced** — surface the opportunity (like the
   sprites checkpoint nag); the user decides.
4. **`know` makes no claims about auth** — it runs the Agent SDK and expects `claude`
   to already work on the box. It does not provision, manage, or prescribe credentials.

## Out of Scope (this pass)

- Hosted / shared-brain option; removing the self-hosted server.
- Vector search or any change to the recall engine.
- Changes to the secretary, OKF curated format, `contradictions`/`resolve`, or the
  secret-in-URL auth model — these all earn their keep and stay untouched.

---

## Component 1 — Remove auto-capture; add propose-and-curate (client plugin)

### Remove
- **`client-plugin/capture.py`** background distiller in full: the detached `claude -p`
  subprocess, per-session offset tracking, `flock` single-flight, debounce subprocess,
  `render_slice`/`already_saved` distill path, and `mcp_save`. The live model in the
  user's session is a better distiller and already holds the conversation.
- **`client-plugin/scrub.py`** — used only by the distiller's client-side saves.
  Confirmed safe to remove: `store.py` scrubs title/body/tags/source server-side on
  every `save`, so model-proposed saves are scrubbed regardless of client.
- The **Stop / SessionEnd** hook entries in `client-plugin/hooks/hooks.json`.

### Add: nudge hook (`UserPromptSubmit`)
A small stdlib-only hook script (replacing `capture.py`) that injects a short
instruction into the turn's context when conditions are met (see Component 2). The
injected text tells the model to — *after* addressing the user's actual message, and
only if it noticed durable facts — surface them as a numbered list and let the user
pick which to save. The instruction is explicit: **never call `save` without an
explicit go-ahead.** If nothing durable is present, say nothing.

Injected marker is a literal `<know-nudge>…</know-nudge>` block so the hook can detect
its own prior injections in the transcript (state without state files).

### Add: `/know:commit` command
`client-plugin/commands/commit.md` — the same propose-and-curate flow, user-invoked on
demand at any time: "scan this conversation for durable team/project facts, show me
candidates as a numbered list, I pick which to save." This is the manual counterpart to
the nudge; both end in the user approving and the model calling `save`.

### Unchanged
`/know:recall`, `/know:ingest`, `/know:contradictions`, `/know:resolve`, `/know:setup`,
the MCP connector wiring (`.mcp.json`, `plugin.json` `mcp_url` config).

---

## Component 2 — Nudge trigger logic (anti-annoyance)

All state is read from the transcript; no state files. A nudge fires on
`UserPromptSubmit` only when **all** hold:

- **Substance:** at least `KNOW_NUDGE_MIN_TURNS` user turns have accrued (default ~6).
- **Spacing:** at least `KNOW_NUDGE_GAP_TURNS` user turns since the last `<know-nudge>`
  marker in the transcript (default ~8).
- **Not already curating:** no `save` tool-call appears since the last nudge marker
  (if the user just saved, they are curating — do not nag).

Declines need no special detection — the spacing gap provides breathing room after a
"no." All thresholds are env-tunable (`KNOW_NUDGE_*`) so the cadence dials down easily,
and the whole nudge can be disabled by setting the gap very high or a dedicated
`KNOW_NUDGE=0`.

The hook fails open and silent: any error (no transcript, parse failure, no config)
results in no injection and no crash — it must never disrupt the user's turn.

---

## Component 3 — `save` tool re-framing (server)

In `server/gateway/mcp_endpoint.py`, the `save` tool description changes from the
current "Call this WITHOUT being asked…" to a user-gated framing:

> Persist a fact the USER has approved saving. Do NOT call this on your own
> initiative — first propose the fact(s) to the user and wait for an explicit
> go-ahead, then save what they approved. One fact per call.

Arguments and validation are unchanged. `recall`, `list`, `supersede`,
`contradictions`, `resolve` descriptions are unchanged.

---

## Component 4 — Drop `/wake`; ride a scheduled command (server)

### Remove
- The `/wake` GET/POST route in `server/gateway/app.py`.
- The external-pinger requirement and `examples/github-actions-wake.yml` (or demote it
  to a documented non-Sprite fallback that runs the CLI).
- The "add an hourly pinger" step on the installer's onboarding card.

### Add: `know wake` CLI
A CLI entrypoint that performs the same three jobs `/wake` did, in-process:
1. **Auth/health:** attempt the work; if the agent errors, send the existing
   `KNOW_ALERT_WEBHOOK` alert (no separate REST probe).
2. **Reconcile:** pull the off-box mirror remote; if it moved, run a curation pass
   (the existing `_curate` / `run_pass` reconcile path).
3. **Liveness:** report curator age + KB inventory (existing `kb_snapshot` /
   `_last_secretary_age`).

The curation keep-alive dance (Sprite tasks API) is preserved inside the reconcile
path. The shared logic currently in `app.py` (`_curate`, `_drain_curate`, mirror pull,
liveness) is factored so both the live save-triggered curation and the `know wake` CLI
call it.

### Scheduling
Podclave Schedules are a control-plane feature — there is no local Sprite API
(`/v1/schedules` 404s) the installer can call to self-register one. So the installer
**prints the exact command to schedule**; the operator wires it:
- **Sprite:** create a Podclave Schedule (control plane) running the printed
  `wake` command hourly (Schedules run a real command and wake a spun-down box).
- **Plain VM:** a `crontab` line running the same command hourly.

The printed command is the venv-python invocation, e.g.
`$HOME/know-gateway/.venv/bin/python $HOME/know-gateway/wake.py`.

---

## Component 5 — `know` makes no claims about auth (server)

The brain runs the Agent SDK; the SDK works iff the box already has working Claude
credentials (the same thing that makes interactive `claude` work). `know` does not
mint keys, manage a key file, set env vars, help anyone log in, or bake credentials
into the service. Whatever auth the operator has is inherited.

### Remove
- In **`install-know.sh`:** the `KEY_FILE` logic, the `die "no ANTHROPIC_API_KEY"`
  hard stop, and baking `ANTHROPIC_API_KEY` into the service `ENVS`. The service
  inherits the operator's environment/credentials (its `HOME` already carries any
  logged-in `~/.claude`).
- In **`boot_check.py`:** the REST `x-api-key` `auth_probe`, `list_models`,
  `model_resolves`, and `resolve_cheapest_haiku` — all REST-and-key bound.

### Replace with a light, non-fatal check
- The existing **end-to-end smoke test** (a real `save` + `recall` that surfaces the
  canary) becomes the auth check: if it works, runtime + auth + model are all good. If
  it fails, **warn clearly but do not crash or block** the install — e.g. "the agent
  couldn't run; make sure `claude` works on this box."
- Keep only the **light SDK-version sanity check** (`sdk_cli_version` / `version_ok`),
  which needs no credentials.
- **Model pinning:** without REST resolution, pin a sane default dated Haiku id
  (`KNOW_MODEL` overridable). The smoke test confirms it resolves.

### Caveat carried into docs
Running a server agent on a personal Max/Pro subscription token is technically fine but
against the spirit of subscription auth. The docs note this so operators choose with
eyes open. `know` neither encourages nor blocks it — it simply uses whatever works.

---

## Component 6 — Pin the KB repo's commit identity locally (server)

The operator's Sprite carries their synced global `~/.gitconfig` (their GitHub
name/email). Today every commit path passes a per-invocation `-c user.name/email`
(store.py `_git`, install seed, secretary, resolver), so the operator is *not*
currently authoring KB commits. But that relies on every path remembering `-c`; any
path that forgets falls through to the synced global. There is no floor.

### Add: a local-config floor
At install, set the KB repo's **local** git config to the `know` bot identity:

```
git -C ~/know-kb config user.name  "know-capture"
git -C ~/know-kb config user.email "capture@know.local"
```

This is `CAPTURE_IDENTITY` (config.py:29) — already a `BOT_EMAILS` member, so a stray
no-`-c` machine commit is correctly classed as bot (not human) by the secretary's
classifier. Local repo config overrides the synced global `~/.gitconfig` for every
commit in the repo, so the operator can never author a KB commit even if a code path
omits the explicit identity.

Critically, `.git/config` is **local-only**: never committed, never pushed to the
mirror, never cloned. The bot identity stays on-box; the operator's synced global never
rides off-box.

### Unchanged
- The two reserved identities (`know-capture`, `know-secretary` @ `know.local`) and the
  per-invocation `-c` that distinguishes capture / secretary / resolver commits — they
  layer on top of the floor.
- The classifier keying on `BOT_EMAILS`. No new config knob; identities stay the fixed
  `@know.local` constants.

### Restore note
The local floor must be (re)applied whenever the KB repo is created or cloned back —
i.e. the installer sets it on a fresh seed **and** on a restore-from-remote clone,
since a clone does not inherit the source repo's local `.git/config`.

## Data Flow (after)

```
User asks about the team/project
   └─ model calls recall (auto-approved) → answers from the brain

Conversation accrues durable facts
   └─ UserPromptSubmit nudge fires (substance + spacing + not-already-curating)
        └─ model, after answering, proposes candidates as a numbered list
             └─ user picks / edits / skips
                  └─ model calls save ONLY on approved items
                       └─ server stores → tail-of-write curation → secretary

Off-box edit pushed to the mirror remote
   └─ hourly `know wake` (Podclave Schedule / crontab)
        └─ pull mirror → reconcile (curation pass) → liveness/alert
```

## Testing

- **Nudge trigger logic:** unit-test the transcript-reading conditions (substance,
  spacing, save-since-last-nudge, fail-open on bad input) with fixture transcripts.
- **`know wake` CLI:** test the factored reconcile/liveness path against a fake repo
  (mirror moved vs. not), reusing the existing `app.py` curation test seams.
- **`save` description:** covered by existing `test_mcp_endpoint.py` tool-list
  assertions (update expected text).
- **Install regression:** `test-install-know.sh` updated for no-key install and the
  warn-don't-die smoke check; assert no `ANTHROPIC_API_KEY` requirement and no `/wake`
  onboarding step.
- **Commit identity floor:** test that after install (fresh seed and restore-clone)
  the KB repo's local `user.email` is the bot identity, and that a commit made with no
  explicit `-c` is authored as the bot — not whatever a (simulated) global gitconfig
  says.
- **Removed code:** delete `test_*` coverage tied to `capture.py` and the REST
  auth/model-resolution helpers.

## Migration / Compatibility

- Existing brains keep working; `/wake` callers (old pingers) can be retired after the
  Schedule/crontab is in place. Optionally leave a `/wake` shim that returns a
  deprecation note for one release — decide in planning.
- Plugin upgrade replaces the Stop/SessionEnd hooks with the `UserPromptSubmit` nudge;
  users on the old version simply stop getting background auto-saves.
```
