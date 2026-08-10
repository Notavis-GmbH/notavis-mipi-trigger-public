"""Tests for :func:`vc_trigger.sensor_controller.discover_sensor`.

The new detection helper adds a catalog-fallback branch to the existing
live-profile lookup. These tests exercise the three-way cascade:

* live profile present  -> ``status == "live"``
* only catalog present  -> ``status == "catalog"``
* neither               -> ``status == "unknown"``

``discover_sensor_profile`` is intentionally left untested here; its
behaviour is already covered by ``test_sensor_controller_profile`` and
must remain byte-compatible (PR #11 does not touch it).
"""

from __future__ import annotations

import subprocess

import pytest

from vc_trigger.sensor_controller import (
    DiscoveryResult,
    discover_sensor,
)


def _patch_sensor_name(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Force ``read_sensor_name`` to return ``name``."""

    class _FakeProc:
        returncode = 0
        stdout = f"sensor_name: '{name}'\n"
        stderr = ""

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", _fake_run)


class TestDiscoverSensorCascade:
    def test_live_profile_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OV9281 has both a live profile and a catalog entry -> ``live``."""
        _patch_sensor_name(monkeypatch, "OV9281")
        result = discover_sensor(run_as_user=None)
        assert isinstance(result, DiscoveryResult)
        assert result.status == "live"
        assert result.is_live is True
        assert result.is_catalog_only is False
        assert result.is_unknown is False
        assert result.sensor_name == "OV9281"
        assert result.profile is not None
        assert result.profile.sensor_name == "OV9281"
        # Catalog is populated in parallel when both sources agree.
        assert result.catalog is not None
        assert result.catalog.sensor_name == "OV9281"

    def test_catalog_only_when_no_live_profile(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """IMX296 is in the catalog but has no live profile -> ``catalog``."""
        _patch_sensor_name(monkeypatch, "IMX296")
        result = discover_sensor(run_as_user=None)
        assert result.status == "catalog"
        assert result.is_catalog_only is True
        assert result.is_live is False
        assert result.is_unknown is False
        assert result.sensor_name == "IMX296"
        assert result.profile is None
        assert result.catalog is not None
        assert result.catalog.sensor_name == "IMX296"
        # Catalog metadata must be usable for the UI banner.
        assert result.catalog.native.width > 0
        assert result.catalog.native.height > 0
        assert result.catalog.shutter in ("global", "rolling")

    def test_unknown_when_neither_registry_matches(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fully unknown sensor -> ``unknown``, no raise."""
        _patch_sensor_name(monkeypatch, "IMX999999_not_a_real_sensor")
        result = discover_sensor(run_as_user=None)
        assert result.status == "unknown"
        assert result.is_unknown is True
        assert result.profile is None
        assert result.catalog is None
        assert result.sensor_name == "IMX999999_not_a_real_sensor"


class TestDiscoverSensorBackwardsCompatibility:
    """``discover_sensor_profile`` must keep its original raising behaviour."""

    def test_unknown_still_raises_via_legacy_helper(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_sensor_name(monkeypatch, "IMX999999_not_a_real_sensor")
        from vc_trigger.sensor_controller import discover_sensor_profile
        from vc_trigger.sensor_profiles_loader import UnknownSensorError

        with pytest.raises(UnknownSensorError):
            discover_sensor_profile(run_as_user=None)
