"""Tests for :mod:`vc_trigger.sensor_controller`.

The controller shells out to ``v4l2-ctl``. We stub ``subprocess.run`` so
tests run entirely off-board.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pydantic import ValidationError

from vc_trigger.models import (
    EXPOSURE_MAX_US,
    EXPOSURE_MIN_US,
    GAIN_MAX,
    GAIN_MIN,
    SENSOR_TRIGGER_MODE_MAX,
    SENSOR_TRIGGER_MODE_MIN,
    SensorParams,
    SensorPixelFormat,
    SensorVendor,
)
from vc_trigger.sensor_controller import (
    SensorController,
    SensorControllerError,
    _extract_fourcc,
    _parse_control_dump,
)


# ---------- parameter model --------------------------------------------------


class TestSensorParams:
    def test_defaults_match_vc_driver_stream_mode(self) -> None:
        p = SensorParams()
        assert p.exposure_us == 10_000
        assert p.gain == 0
        assert p.trigger_mode == 0
        assert p.pixel_format is SensorPixelFormat.RAW10
        assert p.vendor is SensorVendor.OMNIVISION

    def test_exposure_bounds_are_enforced(self) -> None:
        SensorParams(exposure_us=EXPOSURE_MIN_US)
        SensorParams(exposure_us=EXPOSURE_MAX_US)
        with pytest.raises(ValidationError):
            SensorParams(exposure_us=EXPOSURE_MIN_US - 1)
        with pytest.raises(ValidationError):
            SensorParams(exposure_us=EXPOSURE_MAX_US + 1)

    def test_gain_bounds_are_enforced(self) -> None:
        SensorParams(gain=GAIN_MIN)
        SensorParams(gain=GAIN_MAX)
        with pytest.raises(ValidationError):
            SensorParams(gain=GAIN_MIN - 1)
        with pytest.raises(ValidationError):
            SensorParams(gain=GAIN_MAX + 1)

    def test_trigger_mode_bounds_are_enforced(self) -> None:
        SensorParams(trigger_mode=SENSOR_TRIGGER_MODE_MIN)
        SensorParams(trigger_mode=SENSOR_TRIGGER_MODE_MAX)
        with pytest.raises(ValidationError):
            SensorParams(trigger_mode=SENSOR_TRIGGER_MODE_MAX + 1)

    def test_vendor_enum_accepts_sony(self) -> None:
        p = SensorParams(vendor=SensorVendor.SONY)
        assert p.vendor is SensorVendor.SONY


# ---------- parser helpers -------------------------------------------------


def test_parse_control_dump_extracts_key_value_pairs() -> None:
    text = "exposure: 10000\nanalogue_gain: 42\ntrigger_mode: 1\nsensor_name: 'OV9281'\n"
    parsed = _parse_control_dump(text)
    assert parsed == {
        "exposure": "10000",
        "analogue_gain": "42",
        "trigger_mode": "1",
        "sensor_name": "OV9281",
    }


def test_parse_control_dump_ignores_blank_and_garbage_lines() -> None:
    text = "\n---\nexposure: 500\n"
    parsed = _parse_control_dump(text)
    assert parsed == {"exposure": "500"}


def test_extract_fourcc_from_get_fmt_video() -> None:
    body = (
        "Format Video Capture:\n"
        "\tWidth/Height      : 1280/800\n"
        "\tPixel Format      : 'Y10P' (10-bit Greyscale (MIPI Packed))\n"
    )
    assert _extract_fourcc(body) == "Y10P"


# ---------- mock backend ---------------------------------------------------


def test_mock_read_returns_seed_state() -> None:
    ctrl = SensorController(mock=True)
    snap = ctrl.read()
    assert snap.sensor_name == "MOCK_OV9281"
    assert snap.exposure_us == 10_000
    assert snap.gain == 0
    assert snap.trigger_mode == 0
    assert snap.pixel_format is SensorPixelFormat.RAW10


def test_mock_apply_roundtrips_through_read() -> None:
    ctrl = SensorController(mock=True)
    params = SensorParams(
        exposure_us=5000,
        gain=200,
        trigger_mode=1,
        pixel_format=SensorPixelFormat.RAW08,
        vendor=SensorVendor.OMNIVISION,
    )
    ctrl.apply(params)
    snap = ctrl.read()
    assert snap.exposure_us == 5000
    assert snap.gain == 200
    assert snap.trigger_mode == 1
    assert snap.pixel_format is SensorPixelFormat.RAW08


def test_mock_fire_single_trigger_is_side_effect_free() -> None:
    ctrl = SensorController(mock=True)
    before = ctrl.read()
    ctrl.fire_single_trigger()
    after = ctrl.read()
    assert before == after


def test_mock_capture_frames_writes_placeholder_file(tmp_path: Path) -> None:
    ctrl = SensorController(mock=True)
    out = ctrl.capture_frames(
        count=3,
        output_dir=tmp_path,
        pixel_format=SensorPixelFormat.RAW10,
    )
    assert out.exists()
    assert out.read_bytes() == b"\x00" * 32


def test_capture_frames_rejects_non_positive_count(tmp_path: Path) -> None:
    ctrl = SensorController(mock=True)
    with pytest.raises(ValueError):
        ctrl.capture_frames(count=0, output_dir=tmp_path,
                            pixel_format=SensorPixelFormat.RAW10)


# ---------- subprocess wiring ---------------------------------------------


def _fake_completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_read_parses_v4l2_output(run: MagicMock) -> None:
    run.side_effect = [
        _fake_completed(
            0,
            stdout=("exposure: 8000\nanalogue_gain: 100\n"
                    "trigger_mode: 2\nsensor_name: 'OV9281'\n"),
        ),
        _fake_completed(0, stdout=(
            "Format Video Capture:\n"
            "\tPixel Format      : 'GREY' (8-bit Greyscale)\n"
        )),
    ]
    ctrl = SensorController(mock=False, run_as_user=None)
    snap = ctrl.read()
    assert snap.exposure_us == 8000
    assert snap.gain == 100
    assert snap.trigger_mode == 2
    assert snap.sensor_name == "OV9281"
    assert snap.pixel_format is SensorPixelFormat.RAW08


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_apply_writes_exposure_gain_and_pixel_format(run: MagicMock) -> None:
    run.side_effect = [
        _fake_completed(0),  # controls write
        _fake_completed(0),  # pixel format
    ]
    ctrl = SensorController(mock=False, run_as_user=None)
    ctrl.apply(SensorParams(
        exposure_us=1234, gain=42, trigger_mode=1,
        pixel_format=SensorPixelFormat.RAW08,
    ))
    assert run.call_count == 2
    first_argv = run.call_args_list[0].args[0]
    assert "exposure=1234" in first_argv[-1]
    assert "analogue_gain=42" in first_argv[-1]
    assert "trigger_mode=1" in first_argv[-1]
    second_argv = run.call_args_list[1].args[0]
    assert "pixelformat=GREY" in second_argv[-1]


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_apply_surfaces_v4l2_error(run: MagicMock) -> None:
    run.return_value = _fake_completed(
        1, stderr="VIDIOC_S_EXT_CTRLS: failed: Invalid argument"
    )
    ctrl = SensorController(mock=False, run_as_user=None)
    with pytest.raises(SensorControllerError, match="Invalid argument"):
        ctrl.apply(SensorParams())


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_run_v4l2_ctl_uses_sudo_when_run_as_user_differs(run: MagicMock,
                                                          monkeypatch) -> None:
    run.return_value = _fake_completed(0, stdout="")
    monkeypatch.setenv("USER", "raspberrypi")
    ctrl = SensorController(mock=False, run_as_user="notavis")
    ctrl.fire_single_trigger()
    argv = run.call_args.args[0]
    assert argv[:4] == ["sudo", "-n", "-u", "notavis"]
    assert argv[4] == "v4l2-ctl"


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_run_v4l2_ctl_skips_sudo_when_user_matches(run: MagicMock,
                                                     monkeypatch) -> None:
    run.return_value = _fake_completed(0, stdout="")
    monkeypatch.setenv("USER", "notavis")
    ctrl = SensorController(mock=False, run_as_user="notavis")
    ctrl.fire_single_trigger()
    argv = run.call_args.args[0]
    assert argv[0] == "v4l2-ctl"


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_timeout_is_surfaced_as_controller_error(run: MagicMock) -> None:
    run.side_effect = subprocess.TimeoutExpired(cmd="v4l2-ctl", timeout=5)
    ctrl = SensorController(mock=False, run_as_user=None)
    with pytest.raises(SensorControllerError, match="timed out"):
        ctrl.fire_single_trigger()


@patch("vc_trigger.sensor_controller.subprocess.run")
def test_missing_binary_is_surfaced_as_controller_error(run: MagicMock) -> None:
    run.side_effect = FileNotFoundError()
    ctrl = SensorController(mock=False, run_as_user=None)
    with pytest.raises(SensorControllerError, match="not found"):
        ctrl.fire_single_trigger()
