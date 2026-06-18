"""Secret-redaction backstop — canonical patterns live in client-plugin/scrub.py."""
import importlib.util
from pathlib import Path

_PLUGIN_SCRUB = Path(__file__).resolve().parents[2] / "client-plugin" / "scrub.py"
_spec = importlib.util.spec_from_file_location("know_scrub_patterns", _PLUGIN_SCRUB)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SCRUB = _mod.SCRUB
scrub = _mod.scrub

__all__ = ["SCRUB", "scrub"]