"""Scrub pattern tests — gateway is canonical; plugin mirrors (drift guard)."""
import importlib.util
import shutil
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


gateway_scrub = _load(GW / "scrub.py", "know_gateway_scrub")
plugin_scrub = _load(PLUGIN / "scrub.py", "know_plugin_scrub")


def test_scrub_imports_from_deploy_shaped_layout(tmp_path):
    """Mimics ~/know-gateway after install-know.sh — only scrub.py, no client-plugin/."""
    deploy_dir = tmp_path / "know-gateway"
    deploy_dir.mkdir()
    shutil.copy(GW / "scrub.py", deploy_dir / "scrub.py")
    mod = _load(deploy_dir / "scrub.py", "know_deploy_scrub")
    out = mod.scrub("token sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    assert "[REDACTED]" in out
    assert "sk-ant" not in out


def test_store_imports_scrub_on_deploy_layout(tmp_path):
    """store.py:25 imports scrub at boot — must work with only gateway/*.py deployed."""
    deploy = tmp_path / "know-gateway"
    deploy.mkdir()
    for py in GW.glob("*.py"):
        shutil.copy(py, deploy / py.name)
    saved_path = sys.path[:]
    sys.path.insert(0, str(deploy))
    for name in list(sys.modules):
        if name in ("scrub", "store", "config"):
            del sys.modules[name]
    try:
        mod = _load(deploy / "store.py", "know_deploy_store")
        assert mod.scrub("sk-ant-api03-abcdefghijklmnopqrstuvwxyz").startswith("[REDACTED]")
    finally:
        sys.path[:] = saved_path


def test_plugin_scrub_matches_gateway():
    assert len(gateway_scrub.SCRUB) == len(plugin_scrub.SCRUB)
    for inp in (
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "deadbeef" * 8,
    ):
        assert gateway_scrub.scrub(inp) == plugin_scrub.scrub(inp)


def test_plugin_scrub_vendored_fallback_without_gateway(tmp_path):
    """Marketplace install ships only client-plugin/ — must not depend on server/."""
    shutil.copy(PLUGIN / "scrub.py", tmp_path / "scrub.py")
    mod = _load(tmp_path / "scrub.py", "know_plugin_only_scrub")
    out = mod.scrub("sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    assert out == "[REDACTED]"


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


def test_scrub_leaves_benign_text_alone():
    text = "The API gateway is Kong on port 8000, owned by platform."
    assert gateway_scrub.scrub(text) == text


def test_private_key_block_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
    out = gateway_scrub.scrub(pem)
    assert "[REDACTED-PRIVATE-KEY]" in out
    assert "MIIE" not in out
