"""Unit tests for :class:`TriggerController` using the mock backend.

These tests run without any real GPIO hardware. They exercise the state
machine, thread-safety of mode switches, parameter validation, and cleanup.
"""

from __future__ import annotations

import threading
import time

import pytest
from pydantic import ValidationError

from vc_trigger.controller import (
    TriggerController,
    TriggerControllerError,
)
from vc_trigger.models import (
    DUTY_MAX_PCT,
    FREQ_MAX_HZ,
    PULSE_MAX_MS,
    PULSE_MIN_MS,
    PwmParams,
    SingleShotParams,
    TriggerMode,
)


# ---------------------------------------------------------- parameter models --


class TestParameterModels:
    def test_single_shot_default(self) -> None:
        p = SingleShotParams()
        assert p.pulse_ms == 10.0

    def test_single_shot_rejects_below_min(self) -> None:
        with pytest.raises(ValidationError):
            SingleShotParams(pulse_ms=PULSE_MIN_MS / 2)

    def test_single_shot_rejects_above_max(self) -> None:
        with pytest.raises(ValidationError):
            SingleShotParams(pulse_ms=PULSE_MAX_MS + 1)

    def test_pwm_default(self) -> None:
        p = PwmParams()
        assert p.frequency_hz == 100.0
        assert p.duty_cycle_pct == 50.0
        assert p.duty_cycle_fraction == 0.5

    def test_pwm_rejects_frequency_above_limit(self) -> None:
        with pytest.raises(ValidationError):
            PwmParams(frequency_hz=FREQ_MAX_HZ + 1, duty_cycle_pct=50.0)

    def test_pwm_rejects_negative_duty(self) -> None:
        with pytest.raises(ValidationError):
            PwmParams(frequency_hz=100.0, duty_cycle_pct=-1)

    def test_pwm_accepts_boundary_values(self) -> None:
        p = PwmParams(frequency_hz=FREQ_MAX_HZ, duty_cycle_pct=DUTY_MAX_PCT)
        assert p.duty_cycle_fraction == 1.0


# ---------------------------------------------------------- controller basic --


class TestControllerLifecycle:
    def test_starts_idle(self, mock_controller: TriggerController) -> None:
        assert mock_controller.mode == TriggerMode.IDLE
        assert mock_controller.current_pwm is None
        assert mock_controller.last_error is None
        assert mock_controller.pulse_in_flight is False

    def test_single_shot_returns_to_idle(self, mock_controller: TriggerController) -> None:
        mock_controller.fire_single_shot(SingleShotParams(pulse_ms=1.0))
        assert mock_controller.mode == TriggerMode.IDLE
        assert mock_controller.pulse_in_flight is False

    def test_pwm_start_and_stop(self, mock_controller: TriggerController) -> None:
        mock_controller.start_pwm(PwmParams(frequency_hz=50, duty_cycle_pct=25))
        assert mock_controller.mode == TriggerMode.PWM
        assert mock_controller.current_pwm is not None
        assert mock_controller.current_pwm.frequency_hz == 50
        mock_controller.stop()
        assert mock_controller.mode == TriggerMode.IDLE
        assert mock_controller.current_pwm is None

    def test_pwm_can_be_updated_in_place(self, mock_controller: TriggerController) -> None:
        mock_controller.start_pwm(PwmParams(frequency_hz=50, duty_cycle_pct=25))
        first_device = mock_controller._device  # noqa: SLF001 — test-only access
        mock_controller.start_pwm(PwmParams(frequency_hz=120, duty_cycle_pct=60))
        # Same device instance because we updated in place.
        assert mock_controller._device is first_device  # noqa: SLF001
        assert mock_controller.current_pwm.frequency_hz == 120

    def test_shutdown_is_idempotent(self, mock_controller: TriggerController) -> None:
        mock_controller.start_pwm(PwmParams())
        mock_controller.shutdown()
        mock_controller.shutdown()  # must not raise
        assert mock_controller.mode == TriggerMode.IDLE


# ---------------------------------------------------------- mode-switch race --


class TestModeSwitchSafety:
    def test_single_shot_after_pwm_stops_pwm_first(
        self, mock_controller: TriggerController
    ) -> None:
        mock_controller.start_pwm(PwmParams(frequency_hz=50, duty_cycle_pct=50))
        pwm_device = mock_controller._device  # noqa: SLF001
        mock_controller.fire_single_shot(SingleShotParams(pulse_ms=1.0))
        # After the pulse we are back to IDLE, and the PWM device must have
        # been closed (mock's ``close`` flips a flag).
        assert pwm_device.closed is True
        assert mock_controller.mode == TriggerMode.IDLE

    def test_concurrent_pulses_are_serialised(
        self, mock_controller: TriggerController
    ) -> None:
        """A second single-shot while one is running must raise."""

        started_second = threading.Event()
        caught: list[Exception] = []

        def _second() -> None:
            # Wait until the first pulse has definitely started.
            for _ in range(200):
                if mock_controller.pulse_in_flight:
                    break
                time.sleep(0.001)
            try:
                mock_controller.fire_single_shot(SingleShotParams(pulse_ms=1.0))
            except TriggerControllerError as exc:
                caught.append(exc)
            finally:
                started_second.set()

        t = threading.Thread(target=_second)
        t.start()
        # First pulse is long enough for the second thread to collide.
        mock_controller.fire_single_shot(SingleShotParams(pulse_ms=50.0))
        started_second.wait(timeout=2.0)
        t.join(timeout=2.0)

        assert len(caught) == 1
        assert "Puls" in str(caught[0]) or "pulse" in str(caught[0]).lower()


# ---------------------------------------------------------- error surfacing --


class TestErrorSurfacing:
    def test_last_error_cleared_on_success(self, mock_controller: TriggerController) -> None:
        # Force an error state by poking the internal attribute (unit-test scope).
        with mock_controller._lock:  # noqa: SLF001
            mock_controller._last_error = "vorher"  # noqa: SLF001
        mock_controller.start_pwm(PwmParams())
        assert mock_controller.last_error is None
        mock_controller.stop()

    def test_clear_last_error(self, mock_controller: TriggerController) -> None:
        with mock_controller._lock:  # noqa: SLF001
            mock_controller._last_error = "bleibt bis clear"  # noqa: SLF001
        assert mock_controller.last_error == "bleibt bis clear"
        mock_controller.clear_last_error()
        assert mock_controller.last_error is None
