"""Shared configuration + the reserved bot git identities.

The two reserved identities (spec §7.2) are the linchpin of human-edit awareness:
capture + the secretary commit through a wrapper that passes these via per-invocation
`-c user.email`/`-c user.name` (NEVER a clonable gitconfig). The secretary's classifier
(secretary.py) treats ONLY these two exact email strings as bot and fails HUMAN on
everything else — so a human running claude on the box, or a clone that copied a
gitconfig, can never be auto-classed as bot and clobbered.
"""
import os
from pathlib import Path

# Recursion guard: set on the env of every server-side agent invocation so a nested
# hook/agent that checks it bails instead of recursing (belt-and-suspenders; with the
# SDK + setting_sources=None no user hooks load, but kept cheap + explicit).
GUARD_ENV = "KNOW_AGENT"

# The KB data repo (git repo of one-fact-per-file markdown = the truth). Fixed location —
# one brain per host (the installer puts it here); not configurable.
KB_REPO = (Path.home() / "know-kb")

# Teammate-facing secret that lives in the MCP URL path (the credential).
SECRET = os.environ.get("KNOW_SECRET", "").strip()

# Human-readable brain name (set by the installer's --name; shown in healthz/wake/viewer).
NAME = os.environ.get("KNOW_NAME", "know").strip() or "know"

# The brain's public base URL (scheme://host, no path), set by the installer (= the Sprite's
# public URL). Used to build the viewer URL the `viewer` tool returns. If unset, the tool
# falls back to the scheme://host the client dialed.
PUBLIC_URL = os.environ.get("KNOW_PUBLIC_URL", "").strip().rstrip("/")

# Reserved bot identities — (name, email). The email is what the classifier keys on.
CAPTURE_IDENTITY = ("know-capture", "capture@know.local")
SECRETARY_IDENTITY = ("know-secretary", "secretary@know.local")
BOT_EMAILS = {CAPTURE_IDENTITY[1], SECRETARY_IDENTITY[1]}

# Git remote name for the optional backup/restore remote (best-effort push/pull). Constant.
MIRROR_REMOTE = "mirror"

# The Anthropic model the recall/secretary agents run on. The installer pins a concrete
# dated id into the service env (KNOW_MODEL); absent, fall back to the build-time default.
# No evergreen alias — dated ids retire on Anthropic's clock; re-run install to re-pin.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def model_id() -> str:
    """Resolve the pinned model id: KNOW_MODEL env (installer-set) > the build-time default."""
    return os.environ.get("KNOW_MODEL", "").strip() or _DEFAULT_MODEL
