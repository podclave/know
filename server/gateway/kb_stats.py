"""Deterministic KB inventory — cheap counts for healthz/wake/recall observables."""
from pathlib import Path


def _md_count(repo: Path, sub: str, *, exclude_index: bool = False) -> int:
    d = repo / sub
    if not d.is_dir():
        return 0
    files = list(d.glob("*.md"))
    if exclude_index:
        files = [f for f in files if f.name != "index.md"]
    return len(files)


def fact_counts(repo: Path) -> tuple[int, int]:
    """Return (curated_count, raw_count), excluding curated/index.md."""
    return _md_count(repo, "curated", exclude_index=True), _md_count(repo, "raw")


def secretary_behind(curated: int, raw: int) -> bool:
    """True when raw backlog is large relative to curated — secretary may be behind."""
    return bool(raw and (curated == 0 or raw > max(5, curated * 3)))


def kb_snapshot(repo: Path) -> dict:
    """A cheap inventory snapshot for operators (no agent calls)."""
    curated, raw = fact_counts(repo)
    contra_dir = repo / "contradictions"
    open_contra = 0
    if contra_dir.is_dir():
        open_contra = len([f for f in contra_dir.glob("*.md") if f.is_file()])
    return {
        "curated_facts": curated,
        "raw_backlog": raw,
        "open_contradictions": open_contra,
        "secretary_behind": secretary_behind(curated, raw),
    }
