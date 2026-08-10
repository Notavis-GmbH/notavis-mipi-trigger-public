"""Thread-safe GPIO/PWM controller for the VC MIPI trigger.

Wraps gpiozero on top of the ``lgpio`` pin factory (Trixie default). The
controller owns exactly one output device at a time: either a
``PWMOutputDevice`` (for PWM mode) or a ``DigitalOutputDevice`` (for single-
shot mode). Mode switches release the previous device before allocating the
new one, so the pin is never driven twice at once.

Cleanup guarantees:

- ``SIGINT`` / ``SIGTERM`` handlers call :meth:`TriggerController.shutdown`.
- ``atexit`` registers ``shutdown`` as a secondary anchor.
- Every trigger method wraps its device access in ``try/finally``.

The controller MUST be constructed once per process and shared across
threads (Streamlit reruns). Use :func:`get_controller` in application code.
"""

from __future__ import annotations

import atexit
import logging
import signal
import threading
import time
from types import FrameType
from typing import Optional

from .models import PwmParams, SingleShotParams, TriggerMode

_LOG = logging.getLogger(__name__)

DEFAULT_PIN: int = 18  # BCM numbering, hardware-PWM channel 0 on the CM5.


class TriggerControllerError(RuntimeError):
    """Raised when the controller cannot fulfil a request."""


class TriggerController:
    """Owns GPIO 18 and drives it in single-shot or PWM mode.

    All public methods are thread-safe: they acquire an internal lock before
    touching hardware state.
    """

    def __init__(self, pin: int = DEFAULT_PIN, *, mock: bool = False) -> None:
        self._pin = pin
        self._mock = mock
        self._lock = threading.RLock()
        self._mode: TriggerMode = TriggerMode.IDLE
        self._device = None  # type: ignore[assignment]
        self._current_pwm: Optional[PwmParams] = None
        self._last_error: Optional[str] = None
        self._pulse_in_flight: bool = False
        self._install_signal_handlers()
        atexit.register(self.shutdown)
        _LOG.info("TriggerController ready on GPIO %d (mock=%s)", pin, mock)

    # ------------------------------------------------------------------ helpers

    def _install_signal_handlers(self) -> None:
        # Streamlit runs the script in its own thread; only install handlers
        # if we are on the main thread of the main interpreter.
        if threading.current_thread() is not threading.main_thread():
            return

        def _handler(signum: int, _frame: FrameType | None) -> None:
            _LOG.warning("received signal %d — shutting down trigger", signum)
            self.shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Non-main thread or restricted environment — skip silently.
                pass

    def _release_device(self) -> None:
        dev = self._device
        self._device = None
        if dev is None:
            return
        try:
            close = getattr(dev, "close", None)
            if callable(close):
                close()
        except Exception:
            _LOG.exception("error while closing GPIO device")

    def _make_digital_output(self):
        if self._mock:
            return _MockDigitalOutput(self._pin)
        # Local import so tests can run without gpiozero installed.
        from gpiozero import DigitalOutputDevice  # type: ignore
        return DigitalOutputDevice(self._pin, active_high=True, initial_value=False)

    def _make_pwm_output(self, params: PwmParams):
        if self._mock:
            return _MockPwmOutput(self._pin, params)
        from gpiozero import PWMOutputDevice  # type: ignore
        return PWMOutputDevice(
            self._pin,
            active_high=True,
            initial_value=params.duty_cycle_fraction,
            frequency=params.frequency_hz,
        )

    # ------------------------------------------------------------------ status

    @property
    def mode(self) -> TriggerMode:
        with self._lock:
            return self._mode

    @property
    def current_pwm(self) -> Optional[PwmParams]:
        with self._lock:
            return self._current_pwm

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    @property
    def pulse_in_flight(self) -> bool:
        with self._lock:
            return self._pulse_in_flight

    def clear_last_error(self) -> None:
        with self._lock:
            self._last_error = None

    # ------------------------------------------------------------------ actions

    def fire_single_shot(self, params: SingleShotParams) -> None:
        """Emit a single HIGH pulse of the requested duration.

        Blocks the calling thread for ``params.pulse_ms`` milliseconds. UI
        code should call this from a background worker (Streamlit handles
        this transparently: each button click runs on a fresh script pass).
        """
        with self._lock:
            if self._mode == TriggerMode.PWM:
                self._stop_locked()
            if self._pulse_in_flight:
                raise TriggerControllerError("Ein Puls laeuft bereits — bitte warten.")
            self._pulse_in_flight = True
            self._mode = TriggerMode.SINGLE_SHOT
            self._current_pwm = None
            self._release_device()
            try:
                dev = self._make_digital_output()
                self._device = dev
            except Exception as exc:
                self._pulse_in_flight = False
                self._mode = TriggerMode.IDLE
                self._last_error = f"GPIO nicht verfuegbar: {exc}"
                _LOG.error("failed to acquire GPIO %d for single-shot: %s", self._pin, exc)
                raise TriggerControllerError(self._last_error) from exc

        # Drive the pulse OUTSIDE the lock so status polls do not block.
        try:
            dev.on()
            time.sleep(params.pulse_ms / 1000.0)
        finally:
            try:
                dev.off()
            except Exception:
                _LOG.exception("error while driving pin low after pulse")
            with self._lock:
                self._release_device()
                self._pulse_in_flight = False
                self._mode = TriggerMode.IDLE

    def start_pwm(self, params: PwmParams) -> None:
        """Start (or update) a continuous PWM signal on GPIO 18."""
        with self._lock:
            if self._pulse_in_flight:
                raise TriggerControllerError(
                    "Ein Einzel-Puls laeuft gerade — PWM startet nach Abschluss."
                )
            # If already in PWM, adjust in place; otherwise (re-)initialise.
            if self._mode == TriggerMode.PWM and self._device is not None:
                try:
                    self._device.frequency = params.frequency_hz
                    self._device.value = params.duty_cycle_fraction
                    self._current_pwm = params
                    self._last_error = None
                    return
                except Exception as exc:
                    self._last_error = f"PWM-Update fehlgeschlagen: {exc}"
                    _LOG.error("PWM update failed: %s", exc)
                    self._release_device()
                    self._mode = TriggerMode.IDLE
                    raise TriggerControllerError(self._last_error) from exc

            self._release_device()
            try:
                self._device = self._make_pwm_output(params)
                self._mode = TriggerMode.PWM
                self._current_pwm = params
                self._last_error = None
                _LOG.info(
                    "PWM started on GPIO %d: %.2f Hz, duty %.1f%%",
                    self._pin, params.frequency_hz, params.duty_cycle_pct,
                )
            except Exception as exc:
                self._last_error = f"PWM-Start fehlgeschlagen: {exc}"
                _LOG.error("PWM start failed: %s", exc)
                self._release_device()
                self._mode = TriggerMode.IDLE
                raise TriggerControllerError(self._last_error) from exc

    def stop(self) -> None:
        """Stop any active output and drive the pin LOW."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        """Internal: caller must already hold ``self._lock``."""
        was = self._mode
        try:
            dev = self._device
            if dev is not None:
                # For PWM this is essential; for single-shot the pulse routine
                # already turns the pin off, but being idempotent is fine.
                off = getattr(dev, "off", None)
                if callable(off):
                    try:
                        off()
                    except Exception:
                        _LOG.exception("error while turning device off")
        finally:
            self._release_device()
            self._mode = TriggerMode.IDLE
            self._current_pwm = None
            if was != TriggerMode.IDLE:
                _LOG.info("stopped mode=%s on GPIO %d", was.value, self._pin)

    def shutdown(self) -> None:
        """Full teardown — called from signal handlers and atexit."""
        try:
            self.stop()
        except Exception:
            _LOG.exception("error during shutdown")


# --------------------------------------------------------------------- mocks --


class _MockDigitalOutput:
    """Stand-in for gpiozero.DigitalOutputDevice used in tests."""

    def __init__(self, pin: int) -> None:
        self.pin = pin
        self.value = 0
        self.closed = False

    def on(self) -> None:
        self.value = 1

    def off(self) -> None:
        self.value = 0

    def close(self) -> None:
        self.closed = True
        self.value = 0


class _MockPwmOutput:
    """Stand-in for gpiozero.PWMOutputDevice used in tests."""

    def __init__(self, pin: int, params: PwmParams) -> None:
        self.pin = pin
        self.frequency = params.frequency_hz
        self.value = params.duty_cycle_fraction
        self.closed = False

    def off(self) -> None:
        self.value = 0.0

    def close(self) -> None:
        self.closed = True
        self.value = 0.0


# ------------------------------------------------------------------ singleton --


_singleton_lock = threading.Lock()
_singleton: Optional[TriggerController] = None


def get_controller(*, mock: bool = False, pin: int = DEFAULT_PIN) -> TriggerController:
    """Return the process-wide :class:`TriggerController` singleton.

    Streamlit reruns the script on every interaction; the singleton keeps the
    hardware handle across reruns. Tests should pass ``mock=True``.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = TriggerController(pin=pin, mock=mock)
        return _singleton


def reset_controller_for_tests() -> None:
    """Drop the singleton so tests can construct fresh instances."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.shutdown()
        _singleton = None
