"""Tests for the PySide6 desktop UI (mock-mode, offscreen Qt)."""

from __future__ import annotations

import os

import pytest

# conftest.py already sets QT_QPA_PLATFORM=offscreen before Qt import.
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vc_trigger.desktop_ui import _DE, _EN, TriggerWindow  # noqa: E402
from vc_trigger.models import TriggerMode  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_window_opens_and_shows_title(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _DE)
    assert w.windowTitle() == _DE.window_title
    assert w._tabs.count() == 2
    assert w._tabs.tabText(0) == _DE.tab_single
    assert w._tabs.tabText(1) == _DE.tab_pwm
    w.close()


def test_english_strings_render(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _EN)
    assert w.windowTitle() == _EN.window_title
    assert w._tabs.tabText(0) == _EN.tab_single
    w.close()


def test_pwm_start_stop_updates_controller(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _DE)
    w._freq_spin.setValue(50.0)
    w._duty_spin.setValue(30.0)
    w._on_pwm_start()
    assert mock_controller.mode == TriggerMode.PWM
    assert mock_controller.current_pwm is not None
    assert mock_controller.current_pwm.frequency_hz == pytest.approx(50.0)
    assert mock_controller.current_pwm.duty_cycle_pct == pytest.approx(30.0)
    w._on_pwm_stop()
    assert mock_controller.mode == TriggerMode.IDLE
    w.close()


def test_pwm_second_start_is_treated_as_update(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _DE)
    w._on_pwm_start()
    w._freq_spin.setValue(75.0)
    w._on_pwm_start()
    assert mock_controller.current_pwm is not None
    assert mock_controller.current_pwm.frequency_hz == pytest.approx(75.0)
    w.close()


def test_status_refresh_reflects_pwm(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _DE)
    w._freq_spin.setValue(80.0)
    w._duty_spin.setValue(25.0)
    w._on_pwm_start()
    w._refresh_status()
    assert "80.0" in w._status_pwm_label.text()
    assert "25.0" in w._status_pwm_label.text()
    w.close()


def test_close_stops_controller(qapp, mock_controller):
    w = TriggerWindow(mock_controller, _DE)
    w._on_pwm_start()
    assert mock_controller.mode == TriggerMode.PWM
    w.close()
    assert mock_controller.mode == TriggerMode.IDLE
