"""Git-markdown store — the truth (spec §4). One fact per file, append-only raw/,
secretary-owned curated/+INDEX, never-rm _superseded/. All writes scrubbed for
secrets and committed through the env-pinned wrapper (spec §7.2) so the secretary's
classifier can tell capture/secretary commits from human ones.

Layout:
  raw/<slug>-<hex>.md   append-only capture (minimal frontmatter)
  curated/<slug>.md     secretary-promoted, polished
  _superseded/...       retired facts (moved, never deleted)
  INDEX                 secretary-maintained map of the curated set
  CLAUDE.md             the curation methodology (read by the secretary agent)

Methods are sync (git is blocking); the FastAPI handler runs them off the event
loop via asyncio.to_thread.
"""
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from config import CAPTURE_IDENTITY, MIRROR_REMOTE
from scrub import scrub

RAW = "raw"
CURATED = "curated"
SUPERSEDED = "_superseded"
CONTRADICTIONS = "contradictions"
SUBDIRS = (RAW, CURATED, SUPERSEDED, CONTRADICTIONS)


# --- low-level helpers -------------------------------------------------------
def _git(repo: Path, *args, identity=None, check=True) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(repo)]
    if identity:
        name, email = identity
        # per-invocation identity — NEVER written to a clonable gitconfig (spec §7.2)
        cmd += ["-c", f"user.name={name}", "-c", f"user.email={email}"]
    cmd += [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def commit(repo: Path, message: str, identity) -> str | None:
    """Stage everything and commit under `identity`. Returns the new HEAD sha, or
    None if there was nothing to commit (idempotent re-saves don't error)."""
    _git(repo, "add", "-A")
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    _git(repo, "commit", "-m", message, identity=identity)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def push_mirror(repo: Path) -> None:
    """Best-effort push to the private mirror; a missing/unreachable mirror never
    fails a save (the local repo is the truth, the mirror is a backup)."""
    remotes = _git(repo, "remote", check=False).stdout.split()
    if MIRROR_REMOTE not in remotes:
        return
    _git(repo, "push", MIRROR_REMOTE, "HEAD", check=False)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:48].strip("-") or "fact"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# OKF-recommended fields first (type required; resource omitted — know facts are
# rarely resource-bound), then know extension keys (OKF allows + preserves these).
_FM_ORDER = ("type", "title", "description", "resource", "tags", "timestamp",
             "author", "surface", "source", "id")


def render_md(meta: dict, body: str) -> str:
    """Emit an OKF concept doc: a YAML frontmatter block + markdown body. Ordered,
    block-style YAML (matches the OKF reference bundles) so any OKF tool can parse it."""
    fm = {}
    for k in _FM_ORDER:
        v = meta.get(k)
        if v not in (None, "", []):
            fm[k] = v
    for k, v in meta.items():  # preserve any extra producer keys (OKF extensions)
        if k not in fm and v not in (None, "", []):
            fm[k] = v
    block = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True,
                           default_flow_style=False).strip()
    return f"---\n{block}\n---\n\n{body.strip()}\n"


def parse_md(text: str):
    """Return (meta dict, body str). Tolerant of files with no frontmatter and of
    malformed YAML (returns {} meta rather than raising)."""
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    block, body = rest[:end], rest[end + 4:].lstrip("\n")
    try:
        meta = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


# --- the store ----------------------------------------------------------------
class GitStore:
    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def ensure_layout(self):
        """Create the repo skeleton if missing (init handled by the installer in
        production; this keeps tests + first-boot self-heal simple)."""
        if not (self.repo / ".git").exists():
            self.repo.mkdir(parents=True, exist_ok=True)
            _git(self.repo, "init", "-q")
        for d in SUBDIRS:
            p = self.repo / d
            p.mkdir(parents=True, exist_ok=True)
            keep = p / ".gitkeep"
            if not any(p.iterdir()):
                keep.write_text("")

    def _find(self, fact_id: str):
        """Locate the file whose frontmatter id == fact_id, in raw/ or curated/."""
        for sub in (CURATED, RAW):
            d = self.repo / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.md")):
                meta, _ = parse_md(f.read_text())
                if meta.get("id") == fact_id:
                    return f, meta
        return None, None

    # --- write tools ---------------------------------------------------------
    def save(self, title, body, type=None, tags=None, source=None,
             attribution="unknown", surface="mcp") -> dict:
        self.ensure_layout()
        title = scrub(title.strip())
        body = scrub(body.strip())
        if not body:
            raise ValueError("empty fact body")
        fid = os.urandom(4).hex()
        # `type` is OKF's one required field; default to Fact for cheap always-accept
        # capture (the secretary refines it during curation).
        meta = {"type": (type or "Fact").strip() or "Fact", "title": title,
                "tags": [scrub(t) for t in (tags or [])], "timestamp": _now_iso(),
                "author": attribution, "surface": surface,
                "source": scrub(source) if source else None, "id": fid}
        rel = f"{RAW}/{_slug(title)}-{fid}.md"
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_md(meta, body))
        msg = f"capture: {title} [{attribution}/{surface}]"
        commit(self.repo, msg, CAPTURE_IDENTITY)
        push_mirror(self.repo)
        return {"status": "saved", "id": fid, "title": title, "path": rel}

    def list(self, filt: str | None = None) -> dict:
        self.ensure_layout()
        out = []
        for sub in (CURATED, RAW):
            d = self.repo / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.md")):
                if f.name == "index.md":  # OKF reserved file, not a concept
                    continue
                meta, _ = parse_md(f.read_text())
                title = meta.get("title", f.stem)
                tags = meta.get("tags") or []
                if filt:
                    hay = (title + " " + " ".join(map(str, tags))).lower()
                    if filt.lower() not in hay:
                        continue
                out.append({"id": meta.get("id", ""), "title": title,
                            "status": sub, "type": meta.get("type", "Fact"),
                            "tags": tags})
        return {"count": len(out), "facts": out}

    def supersede(self, fact_id, by=None, attribution="unknown") -> dict:
        self.ensure_layout()
        f, meta = self._find(fact_id)
        if not f:
            raise ValueError(f"no fact with id {fact_id}")
        dest_dir = self.repo / SUPERSEDED
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        # never rm — git mv preserves history
        _git(self.repo, "mv", str(f.relative_to(self.repo)),
             str(dest.relative_to(self.repo)), check=False)
        if not dest.exists():  # not tracked yet (uncommitted) — plain move
            f.rename(dest)
        note = f"superseded by {by}" if by else "superseded"
        msg = f"capture: {note}: {meta.get('title', fact_id)} [{attribution}]"
        commit(self.repo, msg, CAPTURE_IDENTITY)
        push_mirror(self.repo)
        return {"status": "superseded", "id": fact_id, "by": by,
                "title": meta.get("title", fact_id)}
