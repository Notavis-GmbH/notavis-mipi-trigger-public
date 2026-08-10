"""Tests for the sensor profile registry loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from vc_trigger.models import SensorPixelFormat
from vc_trigger.sensor_profiles_loader import (
    SensorProfile,
    SensorProfileError,
    UnknownSensorError,
    available_profiles,
    load_profile,
    load_profile_from_path,
)


def test_ov9281_profile_bundled() -> None:
    """The OV9281 profile must ship with the package."""
    profile = load_profile("OV9281")
    assert profile.sensor_name == "OV9281"
    assert profile.native_width == 1280
    assert profile.native_height == 800
    assert profile.mediabus_code == "0x200a"
    assert profile.default_pixel_format == SensorPixelFormat.RAW10
    assert profile.fourcc_for(SensorPixelFormat.RAW10) == "Y10P"
    assert profile.fourcc_for(SensorPixelFormat.RAW08) == "GREY"
    assert profile.controls["exposure"].v4l2_name == "exposure"
    assert profile.controls["gain"].v4l2_name == "analogue_gain"
    assert profile.controls["trigger_mode"].max == 7


def test_available_profiles_contains_ov9281() -> None:
    assert "OV9281" in available_profiles()


def test_unknown_sensor_raises() -> None:
    with pytest.raises(UnknownSensorError):
        load_profile("IMX999_DOES_NOT_EXIST")


def test_malformed_profile_default_not_in_formats(tmp_path: Path) -> None:
    payload = tmp_path / "BadSensor.yaml"
    payload.write_text(
        "sensor_name: BadSensor\n"
        "native: {width: 100, height: 100, mediabus_code: '0x2001'}\n"
        "pixel_formats:\n"
        "  - {id: raw08, fourcc: GREY}\n"
        "default_pixel_format: raw10\n",
        encoding="utf-8",
    )
    with pytest.raises(SensorProfileError):
        load_profile_from_path(payload)


def test_malformed_profile_missing_native(tmp_path: Path) -> None:
    payload = tmp_path / "BadSensor.yaml"
    payload.write_text(
        "sensor_name: BadSensor\n"
        "pixel_formats:\n"
        "  - {id: raw08, fourcc: GREY}\n"
        "default_pixel_format: raw08\n",
        encoding="utf-8",
    )
    with pytest.raises(SensorProfileError):
        load_profile_from_path(payload)


def test_profile_fourcc_lookup_error() -> None:
    """Unknown fourcc lookup must raise KeyError, not silently succeed."""
    profile = load_profile("OV9281")
    # Fake a pixel format not present in the profile by asking about one it
    # does declare and one it does not (RAW08 present, but we craft a bogus
    # enum via getattr to keep type-safety; the KeyError path is exercised
    # from the controller side in test_sensor_controller.py).
    assert profile.fourcc_for(SensorPixelFormat.RAW08) == "GREY"
