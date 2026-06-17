"""Secretary safety-invariant tests. The claude agent is replaced by a fake that
performs scripted file actions, so these verify the DETERMINISTIC guarantees —
never-rm, human-wins, blast-radius, optimistic concurrency, attribution — with no
model in the loop. Quality (does it organize well) is checked live, separately."""
import subprocess

import pytest

import config
import secretary
from store import GitStore, parse_md

HUMAN = ("Some Human", "human@example.com")


@pytest.fixture()
def repo(tmp_path):
    s = GitStore(tmp_path / "kb")
    s.ensure_layout()
    (s.repo / "CLAUDE.md").write_text("# methodology\n- model: test\n")
    # seed curated/index.md via the same generator the pass uses, so an empty pass
    # regenerates identical content (stays a true noop)
    secretary.generate_index(s.repo)
    subprocess.run(["git", "-C", str(s.repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(s.repo), "-c", "user.name=seed",
                    "-c", "user.email=" + config.CAPTURE_IDENTITY[1],
                    "commit", "-q", "-m", "seed"], check=True)
    return s


def _raw_ids(s):
    return [parse_md(f.read_text())[0]["id"] for f in sorted((s.repo / "raw").glob("*.md"))]


def concepts(repo):
    """Curated concept files, excluding the reserved OKF index.md."""
    return [f for f in sorted((repo / "curated").glob("*.md")) if f.name != "index.md"]


def human_commit(repo, relpath, content, msg="human edit"):
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "--", relpath], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", f"user.name={HUMAN[0]}",
                    "-c", f"user.email={HUMAN[1]}", "commit", "-q", "-m", msg], check=True)


def log_authors(repo):
    return subprocess.run(["git", "-C", str(repo), "log", "--format=%ae"],
                          capture_output=True, text=True).stdout.split()


# --- happy path: promote + move + attribution --------------------------------
def test_promotes_raw_moves_to_superseded_commits_as_secretary(repo):
    repo.save("Gateway is Kong", "We use Kong on port 8000", attribution="alice")
    repo.save("DB is Postgres", "Postgres 16", attribution="bob")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        (r / "curated").mkdir(exist_ok=True)
        (r / "curated" / "infra.md").write_text(
            "---\ntype: Architecture\ntitle: Infra\ndescription: core infra\n---\n"
            "Gateway: Kong:8000. DB: Postgres 16.\n")
        return {"incorporated_raw_ids": ids, "contradictions_queued": 0, "summary": "folded infra"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert (repo.repo / "curated" / "infra.md").exists()
    # raw facts moved to _superseded/, none deleted
    assert len(list((repo.repo / "_superseded").glob("*.md"))) == 2
    assert not list((repo.repo / "raw").glob("*.md"))
    assert log_authors(repo.repo)[0] == config.SECRETARY_IDENTITY[1]
    # OKF: index.md regenerated and lists the concept
    assert "Infra" in (repo.repo / "curated" / "index.md").read_text()


# --- never rm: agent deleting a raw file is reverted --------------------------
def test_never_rm_agent_deletion_of_raw_is_reverted(repo):
    repo.save("Fact one", "body one", attribution="alice")
    [fid] = _raw_ids(repo)
    raw_file = next((repo.repo / "raw").glob("*.md"))

    def fake_agent(r, model, prompt, timeout):
        raw_file.unlink()  # forbidden: delete a raw fact
        (r / "curated" / "x.md").write_text("# x\nbody one\n")
        return {"incorporated_raw_ids": [], "summary": "tried to delete raw"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    # the raw fact must still exist (restored), nothing rm'd
    assert raw_file.exists()
    assert "body one" in raw_file.read_text()
    assert res["status"] == "committed"  # the curated/x.md write is allowed


# --- human wins: protected file edits are reverted ---------------------------
def test_human_edited_curated_file_survives_pass(repo):
    repo.save("raw fact", "raw body", attribution="alice")
    ids = _raw_ids(repo)
    # a human authors a curated fact
    human_commit(repo.repo, "curated/owned.md", "# Owned by human\nThe authoritative value is 42.\n")

    def fake_agent(r, model, prompt, timeout):
        # agent tries to clobber the human's curated fact AND make a legit change
        (r / "curated" / "owned.md").write_text("# Clobbered\nThe value is 9999.\n")
        (r / "curated" / "new.md").write_text("# New\nraw body\n")
        return {"incorporated_raw_ids": ids, "summary": "tried to clobber"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    # human content intact, clobber reverted
    assert "authoritative value is 42" in (repo.repo / "curated" / "owned.md").read_text()
    assert "9999" not in (repo.repo / "curated" / "owned.md").read_text()
    # the legit new file still went in
    assert (repo.repo / "curated" / "new.md").exists()
    assert res["status"] == "committed"


# --- blast radius: too many changes bails without committing -----------------
def test_blast_radius_bail(repo):
    repo.save("f", "b", attribution="a")

    def fake_agent(r, model, prompt, timeout):
        for i in range(30):
            (r / "curated" / f"f{i}.md").write_text(f"# f{i}\n")
        return {"incorporated_raw_ids": [], "summary": "too much"}

    before = log_authors(repo.repo)
    res = secretary.run_pass(repo.repo, model="test", max_blast=25, agent=fake_agent)
    assert res["status"] == "bailed" and res["reason"] == "blast_radius_exceeded"
    # nothing committed, working tree clean
    assert log_authors(repo.repo) == before
    assert not concepts(repo.repo)


def _sec_commit(repo, msg="secretary: prior"):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=sec",
                    "-c", "user.email=" + config.SECRETARY_IDENTITY[1],
                    "commit", "-q", "-m", msg], check=True)


# --- contradiction queue: a conflict becomes a structured open record --------
def test_contradiction_filed_as_structured_record_not_overwriting(repo):
    human_commit(repo.repo, "curated/database.md",
                 "---\ntype: Decision\ntitle: Database\n---\nWe use PostgreSQL 16.\n")
    repo.save("Database is MySQL now", "The DB was migrated to MySQL 8", attribution="alice")
    [rid] = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        (r / "contradictions").mkdir(exist_ok=True)
        (r / "contradictions" / "database.md").write_text(
            "---\ntype: Contradiction\nstatus: open\ntarget: database.md\n---\n"
            "Curated: PostgreSQL 16. Conflicting (alice): MySQL 8 migration.\n")
        return {"queued_raw_ids": [rid], "contradictions_queued": 1, "summary": "queued db conflict"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert "PostgreSQL 16" in (repo.repo / "curated" / "database.md").read_text()  # human untouched
    assert (repo.repo / "contradictions" / "database.md").exists()
    assert res["contradictions"]["open"] == 1
    # the conflicting raw fact left the backlog (now captured in the record)
    assert not list((repo.repo / "raw").glob("*.md"))


# --- dequeue: a human edit to the disputed concept closes a PRE-EXISTING record ----
def test_human_edit_closes_open_contradiction(repo):
    # pre-existing curated fact + an open contradiction targeting it (a prior pass)
    (repo.repo / "curated" / "database.md").write_text(
        "---\ntype: Decision\ntitle: Database\n---\nPostgreSQL 16.\n")
    (repo.repo / "contradictions" / "database.md").write_text(
        "---\ntype: Contradiction\nstatus: open\ntarget: database.md\n---\nPostgres vs MySQL.\n")
    _sec_commit(repo.repo, "secretary: prior pass with an open contradiction")
    # the human now edits the disputed concept (resolving it their way)
    human_commit(repo.repo, "curated/database.md",
                 "---\ntype: Decision\ntitle: Database\n---\nPostgreSQL 16 — confirmed, no MySQL migration.\n")

    def fake_agent(r, model, prompt, timeout):
        return {"summary": "nothing new in raw"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert res["contradictions"]["resolved"] == 1 and res["contradictions"]["open"] == 0
    assert not (repo.repo / "contradictions" / "database.md").exists()       # moved out of open
    moved = repo.repo / "contradictions" / "resolved" / "database.md"
    assert moved.exists() and "resolved" in moved.read_text()


# --- optimistic concurrency: a human commit mid-pass defers ------------------
def test_concurrent_human_commit_defers(repo):
    repo.save("f", "b", attribution="a")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        (r / "curated" / "c.md").write_text("# c\nb\n")
        # simulate a human committing WHILE the agent worked (advances HEAD past R)
        human_commit(r, "curated/human.md", "# human landed mid-pass\n")
        return {"incorporated_raw_ids": ids, "summary": "should be deferred"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "deferred" and res["reason"] == "concurrent_human_edit"
    # the secretary's own change was rolled back; the human commit stands
    assert not (repo.repo / "curated" / "c.md").exists()
    assert (repo.repo / "curated" / "human.md").exists()
    assert log_authors(repo.repo)[0] == HUMAN[1]


# --- lying manifest: claims incorporation but wrote nothing -> no raw move ---
def test_claimed_incorporation_without_curated_write_does_not_move_raw(repo):
    repo.save("f", "important body", attribution="alice")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        # reports incorporation but writes NOTHING to curated/ (a lie / empty pass)
        return {"incorporated_raw_ids": ids, "summary": "claims but does nothing"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    # the raw fact must NOT have vanished into _superseded (nothing was actually curated)
    assert list((repo.repo / "raw").glob("*.md")), "raw fact was moved without being curated"
    assert not list((repo.repo / "_superseded").glob("*.md"))
    assert res["status"] == "noop"


# --- mid-pass save: a fact captured WHILE the agent runs is still moved ------
def test_fact_captured_during_pass_is_incorporated_and_moved(repo):
    # no raw at pass start; the "agent" simulates a save landing mid-pass (a capture
    # commit) and curates it. Python must resolve the move against the CURRENT raw/,
    # so the fresh fact leaves raw/ instead of duplicating into raw/ + curated/.
    def fake_agent(r, model, prompt, timeout):
        saved = repo.save("Midpass discovery service", "arrived during the pass", attribution="alice")
        (r / "curated" / "midpass.md").write_text(
            "---\ntype: Fact\ntitle: Midpass discovery service\n---\narrived during the pass\n")
        return {"incorporated_raw_ids": [saved["id"]], "summary": "curated a mid-pass fact"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert not list((repo.repo / "raw").glob("*.md")), "mid-pass fact left duplicated in raw/"
    assert len(list((repo.repo / "_superseded").glob("*.md"))) == 1
    assert (repo.repo / "curated" / "midpass.md").exists()


# --- self-heal: an already-curated raw fact is moved out even with no new write ----
def test_already_curated_raw_fact_is_moved_out(repo):
    saved = repo.save("Kong gateway service", "Kong on port 8000", attribution="a")
    # a prior pass already produced the curated concept (commit it as the secretary)
    (repo.repo / "curated" / "kong-gateway.md").write_text(
        "---\ntype: Architecture\ntitle: Kong gateway service\n---\nKong runs on port 8000.\n")
    subprocess.run(["git", "-C", str(repo.repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo.repo), "-c", "user.name=sec",
                    "-c", "user.email=" + config.SECRETARY_IDENTITY[1],
                    "commit", "-q", "-m", "secretary: prior"], check=True)

    def fake_agent(r, model, prompt, timeout):
        # fact is ALREADY curated -> agent makes NO curated change, just reports it
        return {"incorporated_raw_ids": [saved["id"]], "summary": "already curated"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert not list((repo.repo / "raw").glob("*.md")), "already-curated fact stayed duplicated in raw/"
    assert len(list((repo.repo / "_superseded").glob("*.md"))) == 1


# --- agent failure is clean -------------------------------------------------
def test_agent_error_is_clean_noop(repo):
    repo.save("f", "b", attribution="a")

    def fake_agent(r, model, prompt, timeout):
        return {"_error": "boom"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "error"
    assert list((repo.repo / "raw").glob("*.md"))  # raw untouched


# --- OKF conformance: type is guaranteed even if the agent omits it ----------
def test_missing_type_is_backfilled_for_conformance(repo):
    repo.save("f", "b", attribution="a")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        # agent omits the REQUIRED type field
        (r / "curated" / "thing.md").write_text(
            "---\ntitle: A thing\ndescription: x\n---\nbody\n")
        return {"incorporated_raw_ids": ids, "summary": "no type"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    meta, _ = parse_md((repo.repo / "curated" / "thing.md").read_text())
    assert meta.get("type")  # backfilled -> bundle conforms
    assert res["okf"]["type_backfilled"] == 1


# --- OKF index.md generated, grouped by type ---------------------------------
def test_index_generated_grouped_by_type(repo):
    repo.save("a", "x", attribution="u")
    repo.save("b", "y", attribution="u")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        (r / "curated" / "gw.md").write_text(
            "---\ntype: Architecture\ntitle: Gateway\ndescription: the gw\n---\nKong\n")
        (r / "curated" / "db-choice.md").write_text(
            "---\ntype: Decision\ntitle: DB choice\ndescription: postgres\n---\nPostgres\n")
        return {"incorporated_raw_ids": ids, "summary": "two concepts"}

    secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    idx = (repo.repo / "curated" / "index.md").read_text()
    assert 'okf_version: "0.1"' in idx
    assert "## Architecture" in idx and "## Decision" in idx
    assert "[Gateway](gw.md)" in idx and "[DB choice](db-choice.md)" in idx


# --- OKF cross-links: valid links pass, broken links are reported ------------
def test_cross_links_validated(repo):
    repo.save("a", "x", attribution="u")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        # gw links to db (valid sibling) and to a nonexistent concept + an absolute link
        (r / "curated" / "gw.md").write_text(
            "---\ntype: Architecture\ntitle: Gateway\n---\n"
            "Fronts the [database](db.md). Also see [ghost](ghost.md) and "
            "[bad](/abs.md).\n")
        (r / "curated" / "db.md").write_text(
            "---\ntype: Architecture\ntitle: DB\n---\nPostgres.\n")
        return {"incorporated_raw_ids": ids, "summary": "linked"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    # one valid link (db.md), two broken (ghost.md missing, /abs.md absolute)
    assert res["okf"]["links"] == 3
    assert res["okf"]["broken_links"] == 2
    assert any("ghost.md" in b for b in res["broken_links"])
    assert any("/abs.md" in b for b in res["broken_links"])


# --- AgentResult -> manifest mapping (no SDK call; pure) ---------------------
from agent import AgentResult  # noqa: E402


def test_result_to_manifest_uses_structured_output_and_cost():
    res = AgentResult(structured={"incorporated_raw_ids": ["a", "b"],
                                  "contradictions_queued": 1, "summary": "did it"},
                      cost_usd=0.012, tokens={"in": 100, "out": 20})
    m = secretary._result_to_manifest(res)
    assert m["incorporated_raw_ids"] == ["a", "b"] and m["summary"] == "did it"
    assert m["_cost_usd"] == 0.012 and m["_tokens"] == {"in": 100, "out": 20}


def test_result_to_manifest_is_error():
    m = secretary._result_to_manifest(AgentResult(is_error=True, error="error_max_turns"))
    assert "_error" in m and "error_max_turns" in m["_error"]


def test_result_to_manifest_salvages_from_text_when_no_structured():
    res = AgentResult(text='here {"incorporated_raw_ids": ["x"], "summary": "s"}',
                      cost_usd=0.001)
    m = secretary._result_to_manifest(res)
    assert m["incorporated_raw_ids"] == ["x"] and m["summary"] == "s"


def test_result_to_manifest_no_structured_no_salvage_is_empty_with_cost():
    m = secretary._result_to_manifest(AgentResult(text="just prose, no json", cost_usd=0.002))
    assert m.get("incorporated_raw_ids") is None and m["_cost_usd"] == 0.002


# --- conversational resolution: keep / replace, attribution, human-wins ------
def _open_contradiction(repo, curated_body="PostgreSQL 16.", sources="[dave]"):
    """Seed a curated fact + an open contradiction targeting it, committed as a prior
    (bot) pass — the starting state a `resolve` call acts on."""
    (repo.repo / "curated" / "database.md").write_text(
        f"---\ntype: Decision\ntitle: Database\n---\n{curated_body}\n")
    (repo.repo / "contradictions" / "database.md").write_text(
        "---\ntype: Contradiction\nstatus: open\ntarget: database.md\n"
        f"sources: {sources}\n---\nPostgres vs MySQL dispute.\n")
    _sec_commit(repo.repo, "secretary: prior pass with an open contradiction")


def test_resolve_keep_archives_record_and_leaves_curated(repo):
    _open_contradiction(repo)
    res = secretary.resolve_contradiction(repo.repo, "database.md", "keep",
                                          actor="pat", note="migration was cancelled")
    assert res["status"] == "resolved" and res["decision"] == "keep"
    assert res["curated_updated"] is False
    assert "PostgreSQL 16" in (repo.repo / "curated" / "database.md").read_text()
    assert not (repo.repo / "contradictions" / "database.md").exists()  # out of open
    moved = repo.repo / "contradictions" / "resolved" / "database.md"
    assert moved.exists()
    meta, _ = parse_md(moved.read_text())
    assert meta["status"] == "resolved" and meta["resolved_by"] == "pat"
    assert meta["decision"] == "keep" and meta["resolution_note"] == "migration was cancelled"
    # committed under a NON-bot (human) identity so it rides human-wins
    assert log_authors(repo.repo)[0] not in config.BOT_EMAILS


def test_resolve_replace_updates_curated_preserving_frontmatter(repo):
    _open_contradiction(repo)
    res = secretary.resolve_contradiction(
        repo.repo, "database", "replace",
        text="Primary DB is MySQL 8 (migrated, DBA-approved).", actor="dave")
    assert res["status"] == "resolved" and res["curated_updated"] is True
    cur = (repo.repo / "curated" / "database.md").read_text()
    assert "MySQL 8" in cur and "PostgreSQL 16" not in cur
    meta, _ = parse_md(cur)
    assert meta["type"] == "Decision" and meta["title"] == "Database"  # OKF fm preserved
    assert "[Database](database.md)" in (repo.repo / "curated" / "index.md").read_text()
    assert (repo.repo / "contradictions" / "resolved" / "database.md").exists()
    assert log_authors(repo.repo)[0] not in config.BOT_EMAILS


def test_resolved_replace_survives_a_later_pass(repo):
    """The resolution must STICK: a later pass's agent cannot re-clobber it, because
    the resolve commit is a human edit -> the concept is protected (human-wins)."""
    _open_contradiction(repo)
    secretary.resolve_contradiction(repo.repo, "database.md", "replace",
                                    text="MySQL 8 is the primary database.", actor="dave")

    def fake_agent(r, model, prompt, timeout):
        (r / "curated" / "database.md").write_text(
            "---\ntype: Decision\ntitle: Database\n---\nPostgreSQL 16 again.\n")
        return {"summary": "tried to revert the resolved fact"}

    secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    cur = (repo.repo / "curated" / "database.md").read_text()
    assert "MySQL 8" in cur and "PostgreSQL 16 again" not in cur


def test_resolve_is_mutually_exclusive_with_a_pass(repo):
    import fcntl
    _open_contradiction(repo)
    lock = open(repo.repo / ".git" / "secretary.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = secretary.resolve_contradiction(repo.repo, "database.md", "keep", actor="x")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    assert res["status"] == "busy"
    assert (repo.repo / "contradictions" / "database.md").exists()  # untouched


def test_resolve_unknown_id_raises(repo):
    with pytest.raises(ValueError):
        secretary.resolve_contradiction(repo.repo, "nonexistent.md", "keep", actor="x")


def test_resolve_rejects_bad_decision_and_replace_without_text(repo):
    with pytest.raises(ValueError):
        secretary.resolve_contradiction(repo.repo, "database.md", "delete", actor="a")
    with pytest.raises(ValueError):
        secretary.resolve_contradiction(repo.repo, "database.md", "replace", actor="a")


def test_contradiction_records_lists_only_open(repo):
    _open_contradiction(repo)
    (repo.repo / "contradictions" / "resolved").mkdir(parents=True, exist_ok=True)
    (repo.repo / "contradictions" / "resolved" / "old.md").write_text(
        "---\ntype: Contradiction\nstatus: resolved\ntarget: old.md\n---\nclosed.\n")
    recs = secretary.contradiction_records(repo.repo)
    assert len(recs) == 1
    assert recs[0]["id"] == "database.md" and recs[0]["target"] == "database.md"
    assert recs[0]["sources"] == ["dave"] and "MySQL" in recs[0]["body"]


def test_run_pass_threads_cost_into_result_and_note(repo):
    repo.save("f", "b", attribution="a")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        (r / "curated" / "x.md").write_text("---\ntype: Fact\ntitle: X\n---\nbody\n")
        return {"incorporated_raw_ids": ids, "summary": "with cost",
                "_cost_usd": 0.0042, "_tokens": {"in": 50, "out": 10}}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed" and res["cost_usd"] == 0.0042
    body = subprocess.run(["git", "-C", str(repo.repo), "log", "-1", "--format=%b"],
                          capture_output=True, text=True).stdout
    assert "pass_usd=0.0042" in body
