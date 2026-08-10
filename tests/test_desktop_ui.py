"""Tests for the PySide6 desktop UI.

The whole suite runs headless via ``QT_QPA_PLATFORM=offscreen`` (set in
``conftest.py``). We inject a mock :class:`TriggerController` so no real GPIO
access is attempted and long single-shot pulses do not block the test run.

We drive the widget tree directly (no ``app.exec()``) and verify:

- widgets are constructed and translated in DE by default
- slider ↔ spinbox stay in sync in both directions
- language toggle re-translates every visible label / button
- the fire / start-PWM / stop buttons invoke the injected controller
- entering the PWM page updates the button visibility correctly
- the status panel reflects controller state after actions
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 optional-extra [desktop] not installed")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vc_trigger.controller import TriggerController  # noqa: E402
from vc_trigger.desktop_ui import (  # noqa: E402
    _DE,
    _EN,
    TriggerMainWindow,
    _SingleShotWorker,
)
from vc_trigger.models import PwmParams, SingleShotParams, TriggerMode  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """One QApplication for the entire session; Qt refuses more than one."""
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def window(qapp: QApplication, mock_controller: TriggerController) -> TriggerMainWindow:
    """Fresh window per test, backed by the mock controller fixture."""
    w = TriggerMainWindow(controller=mock_controller)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# Construction & translation
# ---------------------------------------------------------------------------


def test_window_constructs_in_german_by_default(window: TriggerMainWindow) -> None:
    assert window.windowTitle() == _DE.window_title
    assert window._single_fire_button.text() == _DE.single_fire
    assert window._pwm_start_button.text() == _DE.pwm_start
    assert window._pwm_stop_button.text() == _DE.pwm_stop
    assert window._mode_combo.count() == 2
    assert window._mode_combo.itemText(0) == _DE.tab_single
    assert window._mode_combo.itemText(1) == _DE.tab_pwm


def test_language_toggle_retranslates_all_visible_labels(
    window: TriggerMainWindow,
) -> None:
    window._set_language(_EN)

    assert window._single_fire_button.text() == _EN.single_fire
    assert window._pwm_start_button.text() == _EN.pwm_start
    assert window._pwm_stop_button.text() == _EN.pwm_stop
    assert window._mode_combo.itemText(0) == _EN.tab_single
    assert window._mode_combo.itemText(1) == _EN.tab_pwm
    assert window._action_en.isChecked()
    assert not window._action_de.isChecked()

    # Toggle back → DE state restored.
    window._set_language(_DE)
    assert window._single_fire_button.text() == _DE.single_fire
    assert window._action_de.isChecked()


def test_mock_controller_shows_hardware_warning_in_status_bar(
    window: TriggerMainWindow,
) -> None:
    # mock_controller fixture is a mock → warning message must be visible.
    assert window._controller_is_mock() is True
    assert _DE.warn_hw_not_available in window._status_bar.currentMessage()


# ---------------------------------------------------------------------------
# Slider ↔ SpinBox sync (both directions, no feedback loops)
# ---------------------------------------------------------------------------


def test_pulse_slider_drives_spinbox(window: TriggerMainWindow) -> None:
    # scale=10 → slider units are 0.1 ms.
    window._single_pulse_slider.setValue(500)
    assert window._single_pulse_spin.value() == pytest.approx(50.0)


def test_pulse_spinbox_drives_slider(window: TriggerMainWindow) -> None:
    window._single_pulse_spin.setValue(123.4)
    assert window._single_pulse_slider.value() == 1234  # 123.4 * 10


def test_pwm_frequency_and_duty_sync(window: TriggerMainWindow) -> None:
    window._pwm_freq_slider.setValue(150)
    assert window._pwm_freq_spin.value() == pytest.approx(150.0)

    window._pwm_duty_spin.setValue(25.0)
    assert window._pwm_duty_slider.value() == 25


def test_slider_bounds_match_controller_limits(window: TriggerMainWindow) -> None:
    # Pulse: PULSE_MIN_MS=0.1 → slider min = 1 (scale 10)
    assert window._single_pulse_slider.minimum() == 1
    assert window._single_pulse_slider.maximum() == 10000  # 1000 ms * 10
    assert window._pwm_freq_slider.minimum() == 1
    assert window._pwm_freq_slider.maximum() == 200
    assert window._pwm_duty_slider.minimum() == 0
    assert window._pwm_duty_slider.maximum() == 100


# ---------------------------------------------------------------------------
# Controller interaction — fire / start / stop
# ---------------------------------------------------------------------------


def test_start_pwm_calls_controller_and_reports_status(
    window: TriggerMainWindow, mock_controller: TriggerController
) -> None:
    window._pwm_freq_spin.setValue(80.0)
    window._pwm_duty_spin.setValue(40.0)
    window._on_start_pwm()

    assert mock_controller.mode == TriggerMode.PWM
    pwm = mock_controller.current_pwm
    assert pwm is not None
    assert pwm.frequency_hz == pytest.approx(80.0)
    assert pwm.duty_cycle_pct == pytest.approx(40.0)


def test_stop_pwm_returns_controller_to_idle(
    window: TriggerMainWindow, mock_controller: TriggerController
) -> None:
    mock_controller.start_pwm(PwmParams(frequency_hz=50.0, duty_cycle_pct=25.0))
    assert mock_controller.mode == TriggerMode.PWM

    window._on_stop_pwm()
    assert mock_controller.mode == TriggerMode.IDLE
    assert mock_controller.current_pwm is None


def test_single_shot_worker_fires_pulse_directly(
    mock_controller: TriggerController,
) -> None:
    """The worker.run path is exercised synchronously (no QThread) to keep
    the test deterministic and free of event-loop timing."""
    params = SingleShotParams(pulse_ms=0.5)  # tiny pulse → fast
    worker = _SingleShotWorker(mock_controller, params)

    captured: dict[str, float | str] = {}
    worker.finished.connect(lambda ms: captured.setdefault("ms", ms))
    worker.failed.connect(lambda msg: captured.setdefault("err", msg))

    worker.run()
    assert captured.get("ms") == pytest.approx(0.5)
    assert "err" not in captured
    assert mock_controller.mode == TriggerMode.IDLE
    assert mock_controller.last_error is None


def test_single_shot_worker_emits_failed_on_controller_error(
    mock_controller: TriggerController,
) -> None:
    # Poison the controller by pretending a pulse is already in flight;
    # ``fire_single_shot`` rejects overlapping pulses with TriggerControllerError.
    mock_controller._pulse_in_flight = True
    try:
        worker = _SingleShotWorker(
            mock_controller, SingleShotParams(pulse_ms=0.5)
        )

        captured: dict[str, str] = {}
        worker.failed.connect(lambda msg: captured.setdefault("err", msg))
        worker.finished.connect(lambda ms: captured.setdefault("ok", str(ms)))

        worker.run()
        assert "err" in captured
        assert "ok" not in captured
    finally:
        mock_controller._pulse_in_flight = False


# ---------------------------------------------------------------------------
# Status panel reflects controller state
# ---------------------------------------------------------------------------


def test_status_panel_reflects_pwm_active(
    window: TriggerMainWindow, mock_controller: TriggerController
) -> None:
    mock_controller.start_pwm(PwmParams(frequency_hz=120.0, duty_cycle_pct=30.0))
    window._refresh_status()
    # In offscreen mode the window is never realised, so ``isVisible()`` stays
    # False. Use ``isHidden()`` — it reflects the programmatic visibility flag
    # only, which is what we actually control from _refresh_status().
    assert not window._status_pwm_label.isHidden()
    assert "120" in window._status_pwm_label.text()
    assert "30" in window._status_pwm_label.text()


def test_status_panel_hides_pwm_when_idle(
    window: TriggerMainWindow, mock_controller: TriggerController
) -> None:
    # Explicitly ensure controller is idle.
    if mock_controller.mode != TriggerMode.IDLE:
        mock_controller.stop()
    window._refresh_status()
    assert window._status_pwm_label.isHidden()
    assert window._status_pulse_label.isHidden()
    assert window._status_error_label.isHidden()


# ---------------------------------------------------------------------------
# Mode switching
# ---------------------------------------------------------------------------


def test_mode_combo_switches_stacked_page(window: TriggerMainWindow) -> None:
    assert window._pages.currentIndex() == 0
    window._mode_combo.setCurrentIndex(1)
    assert window._pages.currentIndex() == 1
    window._mode_combo.setCurrentIndex(0)
    assert window._pages.currentIndex() == 0


# ---------------------------------------------------------------------------
# Regression: worker + QThread must not be garbage-collected mid-flight
# ---------------------------------------------------------------------------


def test_worker_and_thread_are_retained_while_running(
    qapp: QApplication, mock_controller: TriggerController
) -> None:
    """Regression for a bug where the QThread + _SingleShotWorker were held only
    by locals inside ``_on_fire_single_shot``. Python's GC could reap them
    before the thread had a chance to run, and the pulse silently never fired
    (leaving the fire button disabled forever).

    We verify that once ``_on_fire_single_shot`` returns, both the worker and
    the QThread live on ``self``, and after the pulse completes they are
    cleared and the fire button is re-enabled.
    """
    import gc
    import time

    window = TriggerMainWindow(controller=mock_controller)
    try:
        # A short but non-zero pulse — enough to let the thread actually enter
        # ``worker.run`` before we assert on liveness.
        window._single_pulse_spin.setValue(5.0)
        window._on_fire_single_shot()

        # Immediately after the click handler returns, the worker + thread
        # must be reachable from ``self``. If we only had locals, GC could
        # already have reaped them here.
        assert window._active_worker is not None
        assert window._worker_thread is not None
        assert not window._single_fire_button.isEnabled()

        # Force a GC pass — this is what used to break the buggy version.
        gc.collect()
        assert window._active_worker is not None
        assert window._worker_thread is not None

        # Drive the Qt event loop until ``_clear_worker_thread`` has been
        # invoked (or we time out). Using processEvents in a tight loop keeps
        # the test independent of whether the offscreen platform actually
        # dispatches ``QThread.wait`` — which it sometimes does not.
        deadline = time.monotonic() + 2.0
        while window._worker_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert window._active_worker is None
        assert window._worker_thread is None
        assert window._single_fire_button.isEnabled()
        assert mock_controller.mode == TriggerMode.IDLE
        assert mock_controller.last_error is None
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Sensor tester tab
# ---------------------------------------------------------------------------


from vc_trigger.models import SensorPixelFormat, SensorVendor  # noqa: E402
from vc_trigger.sensor_controller import SensorController  # noqa: E402


@pytest.fixture
def sensor_controller() -> SensorController:
    return SensorController(mock=True)


@pytest.fixture
def sensor_window(
    qapp: QApplication,
    mock_controller: TriggerController,
    sensor_controller: SensorController,
) -> TriggerMainWindow:
    w = TriggerMainWindow(
        controller=mock_controller, sensor_controller=sensor_controller,
    )
    yield w
    w.close()


def test_top_tabs_expose_trigger_and_sensor(sensor_window: TriggerMainWindow) -> None:
    assert sensor_window._top_tabs.count() == 2
    assert sensor_window._top_tabs.tabText(0) == _DE.top_tab_trigger
    assert sensor_window._top_tabs.tabText(1) == _DE.top_tab_sensor


def test_sensor_tab_default_widget_values(sensor_window: TriggerMainWindow) -> None:
    assert sensor_window._sensor_exposure_spin.value() == 10_000
    assert sensor_window._sensor_gain_spin.value() == 0
    assert sensor_window._sensor_trigger_mode_combo.currentData() == 0
    assert sensor_window._sensor_format_combo.currentData() == SensorPixelFormat.RAW10.value
    assert sensor_window._sensor_vendor_omnivision_radio.isChecked()
    assert not sensor_window._sensor_vendor_sony_radio.isChecked()


def test_sensor_apply_writes_through_controller(
    sensor_window: TriggerMainWindow, sensor_controller: SensorController,
) -> None:
    sensor_window._sensor_exposure_spin.setValue(5000)
    sensor_window._sensor_gain_spin.setValue(300)
    sensor_window._sensor_trigger_mode_combo.setCurrentIndex(1)  # ext edge = mode 1
    sensor_window._sensor_format_combo.setCurrentIndex(0)  # RAW08
    sensor_window._sensor_vendor_sony_radio.setChecked(True)

    sensor_window._sensor_apply_button.click()

    snap = sensor_controller.read()
    assert snap.exposure_us == 5000
    assert snap.gain == 300
    assert snap.trigger_mode == 1
    assert snap.pixel_format is SensorPixelFormat.RAW08
    # Log line contains the applied trigger mode
    log_text = sensor_window._sensor_log_view.toPlainText()
    assert "trigger_mode=1" in log_text
    assert "exposure=5000us" in log_text


def test_sensor_read_reflects_state_in_widgets(
    sensor_window: TriggerMainWindow, sensor_controller: SensorController,
) -> None:
    from vc_trigger.models import SensorParams
    # Seed the mock backend with non-default values
    sensor_controller.apply(SensorParams(
        exposure_us=2000, gain=750, trigger_mode=2,
        pixel_format=SensorPixelFormat.RAW08,
    ))
    sensor_window._sensor_read_button.click()

    assert sensor_window._sensor_exposure_spin.value() == 2000
    assert sensor_window._sensor_gain_spin.value() == 750
    assert sensor_window._sensor_trigger_mode_combo.currentData() == 2
    assert sensor_window._sensor_format_combo.currentData() == SensorPixelFormat.RAW08.value


def test_sensor_capture_writes_file_and_logs(
    sensor_window: TriggerMainWindow, tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr("vc_trigger.desktop_ui.Path.home", lambda: tmp_path)
    sensor_window._sensor_capture_count_spin.setValue(5)
    sensor_window._sensor_capture_button.click()

    log_text = sensor_window._sensor_log_view.toPlainText()
    assert "5 frames" in log_text
    # File exists under $HOME/vc-trigger-logs/
    files = list((tmp_path / "vc-trigger-logs").glob("*.raw"))
    assert files, "capture file should have been created"


def test_sensor_clear_log_empties_the_view(sensor_window: TriggerMainWindow) -> None:
    sensor_window._sensor_apply_button.click()
    assert sensor_window._sensor_log_view.toPlainText() != ""
    sensor_window._sensor_clear_log_button.click()
    assert sensor_window._sensor_log_view.toPlainText() == ""


def test_language_toggle_covers_sensor_tab(sensor_window: TriggerMainWindow) -> None:
    sensor_window._action_en.trigger()
    assert sensor_window._top_tabs.tabText(1) == _EN.top_tab_sensor
    assert sensor_window._sensor_read_button.text() == _EN.sensor_read_button
    assert sensor_window._sensor_apply_button.text() == _EN.sensor_apply_button
    assert sensor_window._sensor_capture_button.text() == _EN.sensor_capture_button
