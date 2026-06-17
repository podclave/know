"""Render the curated OKF bundle as a single self-contained interactive graph (HTML).

Adapted from the OKF reference visualizer
(github.com/GoogleCloudPlatform/knowledge-catalog, okf/src/enrichment_agent/viewer,
Apache-2.0 — see NOTICE). Changes: parse frontmatter with teamkb's own `store.parse_md`
(no enrichment_agent dependency), use teamkb's concept-type palette, and return the HTML
as a string for on-demand serving rather than writing a file. The bundled viz.html /
viz.css / viz.js are the upstream assets, vendored verbatim.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from store import parse_md

_DIR = Path(__file__).parent
_INDEX_NAME = "index.md"
_LINK_RE = re.compile(r"\]\(([^)\s]+\.md)(?:#[A-Za-z0-9_\-]*)?\)")

# teamkb concept types -> node colors (unknown types fall back to slate).
_TYPE_PALETTE = {
    "Fact": "#3b82f6",
    "Decision": "#8b5cf6",
    "Convention": "#10b981",
    "Gotcha": "#ef4444",
    "Runbook": "#f59e0b",
    "Architecture": "#06b6d4",
    "Reference": "#64748b",
}
_DEFAULT_NODE_COLOR = "#94a3b8"


@dataclass
class Concept:
    id: str
    type: str
    title: str
    description: str
    resource: str
    tags: list[str]
    body: str
    links_to: list[str] = field(default_factory=list)

    def to_node(self) -> dict[str, Any]:
        return {"data": {
            "id": self.id, "label": self.title or self.id, "type": self.type,
            "description": self.description, "resource": self.resource, "tags": self.tags,
            "color": _TYPE_PALETTE.get(self.type, _DEFAULT_NODE_COLOR),
            "size": 30 + min(60, len(self.body) // 200)}}


def _extract_links(body: str, doc_dir: Path, bundle_root: Path) -> list[str]:
    out, seen = [], set()
    root = bundle_root.resolve()
    for m in _LINK_RE.finditer(body):
        target = m.group(1)
        if "://" in target or target.startswith("/"):
            continue
        try:
            resolved = (doc_dir / target).resolve().relative_to(root)
        except ValueError:
            continue
        rel = resolved.as_posix()
        if rel.endswith(".md"):
            rel = rel[:-3]
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _walk_concepts(bundle_root: Path) -> list[Concept]:
    concepts = []
    for md_path in sorted(bundle_root.rglob("*.md")):
        if md_path.name == _INDEX_NAME:
            continue
        rel = md_path.relative_to(bundle_root).with_suffix("")
        fm, body = parse_md(md_path.read_text(encoding="utf-8"))
        fm = fm or {}
        tags = fm.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        concepts.append(Concept(
            id="/".join(rel.parts), type=str(fm.get("type") or "Unknown"),
            title=str(fm.get("title") or "/".join(rel.parts)),
            description=str(fm.get("description") or ""),
            resource=str(fm.get("resource") or ""),
            tags=[str(t) for t in tags], body=body or "",
            links_to=_extract_links(body or "", md_path.parent, bundle_root)))
    return concepts


def _build_graph(concepts: list[Concept]) -> dict[str, Any]:
    ids = {c.id for c in concepts}
    edges, seen = [], set()
    for c in concepts:
        for target in c.links_to:
            if target == c.id or target not in ids or (c.id, target) in seen:
                continue
            seen.add((c.id, target))
            edges.append({"data": {"id": f"{c.id}__{target}", "source": c.id, "target": target}})
    return {"nodes": [c.to_node() for c in concepts], "edges": edges,
            "bodies": {c.id: c.body for c in concepts},
            "types": sorted({c.type for c in concepts}), "palette": _TYPE_PALETTE}


def generate_html(bundle_root: Path, bundle_name: str = "teamkb") -> str:
    """Walk the OKF bundle at `bundle_root` and return a single self-contained HTML
    visualization (no backend; cytoscape + marked load from CDN in the browser)."""
    bundle_root = Path(bundle_root)
    concepts = _walk_concepts(bundle_root) if bundle_root.is_dir() else []
    graph = _build_graph(concepts)
    template = (_DIR / "templates" / "viz.html").read_text(encoding="utf-8")
    css = (_DIR / "static" / "viz.css").read_text(encoding="utf-8")
    js = (_DIR / "static" / "viz.js").read_text(encoding="utf-8")
    return (template
            .replace("/*__VIZ_CSS__*/", css)
            .replace("/*__VIZ_JS__*/", js)
            .replace("__BUNDLE_NAME__", json.dumps(bundle_name))
            .replace("__BUNDLE_DATA__", json.dumps(graph)))
