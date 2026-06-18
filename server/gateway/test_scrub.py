"""Scrub pattern tests — canonical patterns in client-plugin/scrub.py, re-exported by gateway."""
import importlib.util
import sys
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent
PLUGIN = GW.parents[1] / "client-plugin"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plugin_scrub = _load(PLUGIN / "scrub.py", "know_plugin_scrub")
gateway_scrub = _load(GW / "scrub.py", "know_gateway_scrub")


def test_gateway_reexports_same_pattern_count():
    assert len(gateway_scrub.SCRUB) == len(plugin_scrub.SCRUB)


@pytest.mark.parametrize("inp,needle", [
    ("key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "[REDACTED]"),
    ("token ghp_abcdefghijklmnopqrstuvwxyz1234567890", "[REDACTED]"),
    ("slack xoxb-1234567890-abcdefghij", "[REDACTED]"),
    ("aws AKIAIOSFODNN7EXAMPLE", "[REDACTED]"),
    ("db://user:supersecret@host/db", "[REDACTED]"),
    ("MY_API_KEY=not-a-real-secret-value-here", "[REDACTED]"),
    ("deadbeef" * 8, "[REDACTED]"),
])
def test_scrub_redacts_common_secret_shapes(inp, needle):
    assert needle in gateway_scrub.scrub(inp)
    assert gateway_scrub.scrub(inp) == plugin_scrub.scrub(inp)


def test_scrub_leaves_benign_text_alone():
    text = "The API gateway is Kong on port 8000, owned by platform."
    assert gateway_scrub.scrub(text) == text


def test_private_key_block_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
    out = gateway_scrub.scrub(pem)
    assert "[REDACTED-PRIVATE-KEY]" in out
    assert "MIIE" not in out