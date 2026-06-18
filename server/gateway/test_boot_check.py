"""Boot-check helpers — mocked HTTP, no live Anthropic calls."""
import os
from unittest.mock import MagicMock, patch

import boot_check


def test_auth_probe_missing_key():
    with patch.dict(os.environ, {}, clear=True):
        ok, msg = boot_check.auth_probe()
    assert ok is False
    assert "not set" in msg


def test_auth_probe_ok():
    mock_resp = MagicMock(status_code=200)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        with patch("boot_check.httpx.get", return_value=mock_resp):
            ok, msg = boot_check.auth_probe()
    assert ok is True
    assert msg == "ok"


def test_auth_probe_rejected():
    mock_resp = MagicMock(status_code=401, text="nope")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-bad"}):
        with patch("boot_check.httpx.get", return_value=mock_resp):
            ok, msg = boot_check.auth_probe()
    assert ok is False
    assert "auth rejected" in msg


def test_model_resolves_true():
    mock_resp = MagicMock(status_code=200)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        with patch("boot_check.httpx.get", return_value=mock_resp):
            assert boot_check.model_resolves("claude-haiku-4-5-20251001") is True


def test_resolve_cheapest_haiku_picks_latest_dated():
    models = [
        "claude-haiku-4-5-20251001",
        "claude-haiku-4-5-20251101",
        "claude-sonnet-4-20250514",
    ]
    with patch("boot_check.list_models", return_value=models):
        assert boot_check.resolve_cheapest_haiku() == "claude-haiku-4-5-20251101"


def test_version_ok_below_floor_fails():
    with patch("boot_check.sdk_cli_version", return_value="2.0.0"):
        ok, msg = boot_check.version_ok("2.1.92")
    assert ok is False
    assert "below" in msg