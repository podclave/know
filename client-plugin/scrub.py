"""Secret-redaction patterns for the capture hook — mirrors server/gateway/scrub.py.

When developing in the monorepo, prefer loading the gateway copy so there is a
single source of truth. Marketplace installs ship only client-plugin/, so a
vendored fallback is required. test_scrub.py enforces parity between the two.
"""
import importlib.util
import re
from pathlib import Path

_VENDORED = [
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S), '[REDACTED-PRIVATE-KEY]'),
    (re.compile(r'sk-(?:ant-)?[A-Za-z0-9_-]{12,}'), '[REDACTED]'),
    (re.compile(r'gh[posru]_[A-Za-z0-9]{20,}'), '[REDACTED]'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '[REDACTED]'),
    (re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'), '[REDACTED-JWT]'),
    (re.compile(r'\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)[^/\s:@]+(@)'), r'\1[REDACTED]\2'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED]'),
    (re.compile(r'([A-Za-z0-9_-]*(?:SECRET|TOKEN|PASSWORD|API_KEY|APIKEY)[A-Za-z0-9_-]*[=:]\s*)[^\s"]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'\b[0-9a-f]{32,}\b'), '[REDACTED]'),
]


def _load_gateway_scrub():
    gw = Path(__file__).resolve().parents[1] / "server" / "gateway" / "scrub.py"
    if not gw.is_file():
        return None
    spec = importlib.util.spec_from_file_location("know_gateway_scrub", gw)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_gw = _load_gateway_scrub()
SCRUB = _gw.SCRUB if _gw else _VENDORED


def scrub(s: str) -> str:
    if _gw:
        return _gw.scrub(s)
    for rx, rep in SCRUB:
        s = rx.sub(rep, s)
    return s
