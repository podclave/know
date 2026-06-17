"""Shared configuration + the reserved bot git identities.

The two reserved identities (spec §7.2) are the linchpin of human-edit awareness:
capture + the secretary commit through a wrapper that passes these via per-invocation
`-c user.email`/`-c user.name` (NEVER a clonable gitconfig). The secretary's classifier
(secretary.py) treats ONLY these two exact email strings as bot and fails HUMAN on
everything else — so a human running claude on the box, or a clone that copied a
gitconfig, can never be auto-classed as bot and clobbered.
"""
import os
import shutil
from pathlib import Path


def claude_bin() -> str:
    """Resolve the `claude` executable. The recall/secretary agents shell out to it;
    a supervised service can have a minimal PATH, so fall back to the standard install
    location. CLAUDE_BIN overrides."""
    return (os.environ.get("CLAUDE_BIN")
            or shutil.which("claude")
            or str(Path.home() / ".local" / "bin" / "claude"))

# The KB data repo (git repo of one-fact-per-file markdown = the truth).
KB_REPO = Path(os.environ.get("BRAIN_KB_REPO", str(Path.home() / "brain-kb"))).expanduser()

# Teammate-facing secret that lives in the MCP URL path (the credential).
SECRET = os.environ.get("BRAIN_SECRET", "").strip()

# Human-readable brain/team name (onboarding cards, commit context).
BRAIN_NAME = os.environ.get("BRAIN_NAME", "teamkb").strip() or "teamkb"

# Reserved bot identities — (name, email). The email is what the classifier keys on.
CAPTURE_IDENTITY = ("teamkb-capture", "capture@teamkb.local")
SECRETARY_IDENTITY = ("teamkb-secretary", "secretary@teamkb.local")
BOT_EMAILS = {CAPTURE_IDENTITY[1], SECRETARY_IDENTITY[1]}

# Mirror remote name (private GitHub mirror; push is best-effort).
MIRROR_REMOTE = os.environ.get("BRAIN_MIRROR_REMOTE", "mirror").strip() or "mirror"

# The Anthropic model the recall/secretary agents run on. Resolved to a concrete
# dated id at install and recorded on the model line of KB_REPO/CLAUDE.md (spec §5.2);
# env override wins. No evergreen alias — dated ids retire on Anthropic's clock.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def model_id(kb_repo: Path | None = None) -> str:
    """Resolve the pinned model id: env override > the recorded line in the KB
    repo's CLAUDE.md (`model: <id>`) > the build-time default."""
    env = os.environ.get("BRAIN_MODEL", "").strip()
    if env:
        return env
    repo = kb_repo or KB_REPO
    claude_md = repo / "CLAUDE.md"
    try:
        for line in claude_md.read_text().splitlines():
            s = line.strip()
            # Match a "model: <id>" line (markdown bullet or bare), case-insensitive key.
            low = s.lower().lstrip("-* ").strip()
            if low.startswith("model:"):
                val = s.split(":", 1)[1].strip().strip("`")
                if val:
                    return val
    except OSError:
        pass
    return _DEFAULT_MODEL
