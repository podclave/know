"""Scrub pattern tests — the gateway is the only scrub copy now (the client plugin no longer vendors one)."""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gateway_scrub = _load(GW / "scrub.py", "know_gateway_scrub")


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
