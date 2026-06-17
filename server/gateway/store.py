"""Git-markdown store — the truth (spec §4). One fact per file, append-only raw/,
secretary-owned curated/+INDEX, never-rm _superseded/. All writes scrubbed for
secrets and committed through the env-pinned wrapper (spec §7.2) so the secretary's
classifier can tell capture/secretary commits from human ones.

Layout:
  raw/<slug>-<hex>.md   append-only capture (minimal frontmatter)
  curated/<slug>.md     secretary-promoted, polished
  _superseded/...       retired facts (moved, never deleted)
  INDEX                 secretary-maintained map of the curated set
  CLAUDE.md             the methodology + the one pinned model/version line

Methods are sync (git is blocking); the FastAPI handler runs them off the event
loop via asyncio.to_thread.
"""
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from config import CAPTURE_IDENTITY, MIRROR_REMOTE
from scrub import scrub

RAW = "raw"
CURATED = "curated"
SUPERSEDED = "_superseded"
SUBDIRS = (RAW, CURATED, SUPERSEDED)


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


_FM_KEYS = ("id", "title", "author", "surface", "date", "aliases", "source")


def render_md(meta: dict, body: str) -> str:
    lines = ["---"]
    for k in _FM_KEYS:
        v = meta.get(k)
        if v in (None, "", []):
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def parse_md(text: str):
    """Return (meta dict, body str). Tolerant of files with no frontmatter."""
    meta, body = {}, text
    if text.startswith("---"):
        rest = text[3:].lstrip("\n")
        end = rest.find("\n---")
        if end != -1:
            block = rest[:end]
            body = rest[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    if isinstance(meta.get("aliases"), str):
        meta["aliases"] = [a.strip() for a in meta["aliases"].split(",") if a.strip()]
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
    def save(self, title, body, aliases=None, source=None, attribution="unknown",
             surface="mcp") -> dict:
        self.ensure_layout()
        title = scrub(title.strip())
        body = scrub(body.strip())
        if not body:
            raise ValueError("empty fact body")
        fid = os.urandom(4).hex()
        meta = {"id": fid, "title": title, "author": attribution,
                "surface": surface, "date": _now_iso(),
                "aliases": [scrub(a) for a in (aliases or [])],
                "source": scrub(source) if source else None}
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
                meta, _ = parse_md(f.read_text())
                title = meta.get("title", f.stem)
                aliases = meta.get("aliases") or []
                if filt:
                    hay = (title + " " + " ".join(aliases)).lower()
                    if filt.lower() not in hay:
                        continue
                out.append({"id": meta.get("id", ""), "title": title,
                            "status": sub, "aliases": aliases})
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
