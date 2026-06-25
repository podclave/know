"""Boot-check helpers — credential-free SDK-runtime checks only.

`know` makes no claims about auth (it just expects `claude` to work on the box), so the
REST x-api-key auth probe and REST model-resolution were removed. The real auth+model
validation is the install-time save+recall smoke test, which warns (does not die)."""
from unittest.mock import patch

import boot_check


def test_version_ok_below_floor_fails():
    with patch("boot_check.sdk_cli_version", return_value="2.0.0"):
        ok, msg = boot_check.version_ok("2.1.92")
    assert ok is False
    assert "below" in msg


def test_version_ok_at_floor_passes():
    with patch("boot_check.sdk_cli_version", return_value="2.1.92"):
        ok, msg = boot_check.version_ok("2.1.92")
    assert ok is True
    assert msg == "2.1.92"


def test_version_ok_recorded_mismatch_fails():
    with patch("boot_check.sdk_cli_version", return_value="2.2.0"):
        ok, msg = boot_check.version_ok("2.1.92", recorded="2.1.99")
    assert ok is False
    assert "recorded" in msg


def test_full_check_passes_on_good_runtime(capsys):
    with patch("boot_check.sdk_cli_version", return_value="2.1.92"):
        rc = boot_check.full_check("2.1.92")
    assert rc == 0
    assert "agent runtime" in capsys.readouterr().out


def test_no_rest_auth_surface_remains():
    # the credential-bound REST helpers are gone
    for gone in ("auth_probe", "list_models", "model_resolves", "resolve_cheapest_haiku"):
        assert not hasattr(boot_check, gone)
