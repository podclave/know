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


# --- contradiction queue -----------------------------------------------------
def test_contradiction_queued_not_overwritten(repo):
    human_commit(repo.repo, "curated/db.md", "# Database\nWe use Postgres.\n")
    repo.save("db is mysql", "Actually the DB is MySQL now", attribution="alice")
    ids = _raw_ids(repo)

    def fake_agent(r, model, prompt, timeout):
        # respects human file; files the conflict instead of overwriting
        (r / "CONTRADICTIONS.md").write_text(
            "## Database\n- curated: Postgres\n- raw(alice): MySQL\n")
        return {"incorporated_raw_ids": ids, "contradictions_queued": 1, "summary": "queued db conflict"}

    res = secretary.run_pass(repo.repo, model="test", agent=fake_agent)
    assert res["status"] == "committed"
    assert "Postgres" in (repo.repo / "curated" / "db.md").read_text()  # human untouched
    assert (repo.repo / "CONTRADICTIONS.md").exists()
    assert "MySQL" in (repo.repo / "CONTRADICTIONS.md").read_text()


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
