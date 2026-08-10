"""Tests for the profile-aware behaviour of :class:`SensorController`.

Kept separate from ``test_sensor_controller.py`` so the profile-registry
changes stay small and reviewable.
"""

from __future__ import annotations

from vc_trigger.models import SensorPixelFormat
from vc_trigger.sensor_controller import SensorController, read_sensor_name
from vc_trigger.sensor_profiles_loader import load_profile


class TestSensorControllerWithProfile:
    def test_legacy_mode_maps_raw10_to_y10p(self) -> None:
        """Without a profile the controller falls back to the legacy fourcc map."""
        ctrl = SensorController(mock=True)
        assert ctrl.profile is None
        assert ctrl._fourcc_for(SensorPixelFormat.RAW10) == "Y10P"
        assert ctrl._fourcc_for(SensorPixelFormat.RAW08) == "GREY"

    def test_profile_drives_fourcc_mapping(self) -> None:
        profile = load_profile("OV9281")
        ctrl = SensorController(mock=True, profile=profile)
        assert ctrl.profile is profile
        # OV9281 profile pins RAW10 -> Y10P and RAW08 -> GREY.
        assert ctrl._fourcc_for(SensorPixelFormat.RAW10) == "Y10P"
        assert ctrl._fourcc_for(SensorPixelFormat.RAW08) == "GREY"


class TestReadSensorName:
    """Regression: ``read_sensor_name`` parses the v4l2-ctl control dump."""

    def test_parses_control_dump(self, monkeypatch) -> None:
        """The helper must strip the ``sensor_name: 'OV9281'`` line correctly."""
        import subprocess

        class _FakeProc:
            returncode = 0
            stdout = "sensor_name: 'OV9281'\n"
            stderr = ""

        def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            return _FakeProc()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert read_sensor_name("/dev/v4l-subdev2", run_as_user=None) == "OV9281"
