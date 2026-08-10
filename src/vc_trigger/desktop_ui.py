"""PySide6 desktop UI for the GPIO/PWM camera trigger.

Functionally equivalent to :mod:`vc_trigger.ui` (the Streamlit web UI). Both
frontends share the same :class:`TriggerController` and Pydantic parameter
models, so behaviour on GPIO 18 is identical.

Run with::

    python3 -m vc_trigger.desktop_ui
    vc-trigger-desktop      # entry point from pyproject.toml

Environment:

- ``VC_TRIGGER_MOCK=1`` — use the mock GPIO backend (development off-board).
- ``QT_QPA_PLATFORM=offscreen`` — headless Qt (used by the test suite).

All hardware actions require an explicit button click. Slider changes on their
own never touch the pin. The blocking single-shot pulse runs in a
:class:`QThread` worker so the UI stays responsive.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .controller import TriggerController, TriggerControllerError, get_controller
from .logging_setup import configure_logging
from .models import (
    DUTY_MAX_PCT,
    DUTY_MIN_PCT,
    FREQ_MAX_HZ,
    FREQ_MIN_HZ,
    PULSE_MAX_MS,
    PULSE_MIN_MS,
    PwmParams,
    SingleShotParams,
    TriggerMode,
)

_LOG = logging.getLogger(__name__)

_PRIMARY_QSS = (
    "QPushButton { background-color: #01696F; color: white; padding: 8px 16px;"
    " font-weight: 600; border-radius: 4px; }"
    " QPushButton:hover { background-color: #0C4E54; }"
    " QPushButton:disabled { background-color: #BAB9B4; }"
)
_SECONDARY_QSS = (
    "QPushButton { padding: 8px 16px; border-radius: 4px; border: 1px solid #D4D1CA; }"
)


# --------------------------------------------------------------- language ----


@dataclass(frozen=True)
class Strings:
    window_title: str
    subtitle: str
    menu_language: str
    lang_de: str
    lang_en: str
    tab_single: str
    tab_pwm: str
    single_header: str
    single_pulse_label: str
    single_fire: str
    pwm_header: str
    pwm_freq_label: str
    pwm_duty_label: str
    pwm_start: str
    pwm_stop: str
    status_header: str
    status_mode: str
    status_current_pwm: str
    status_last_error: str
    status_pulse_running: str
    status_idle: str
    ok_pulse_fired: str
    ok_pwm_started: str
    ok_pwm_updated: str
    ok_stopped: str
    warn_hw_not_available: str
    err_hw_dialog_title: str


_DE = Strings(
    window_title="NOTAVIS Trigger — GPIO 18",
    subtitle="Externer Kamera-Trigger auf Raspberry Pi (Hardware-PWM).",
    menu_language="Sprache",
    lang_de="Deutsch",
    lang_en="Englisch",
    tab_single="Einzel-Puls",
    tab_pwm="Kontinuierliches PWM",
    single_header="Einzel-Puls (Single-Shot)",
    single_pulse_label=f"Pulsdauer (ms) — {PULSE_MIN_MS:.1f} bis {PULSE_MAX_MS:.0f}",
    single_fire="Trigger manuell ausloesen",
    pwm_header="Kontinuierliches PWM-Signal",
    pwm_freq_label=f"Frequenz (Hz) — {FREQ_MIN_HZ:.0f} bis {FREQ_MAX_HZ:.0f}",
    pwm_duty_label=f"Duty Cycle (%) — {DUTY_MIN_PCT:.0f} bis {DUTY_MAX_PCT:.0f}",
    pwm_start="PWM starten / aktualisieren",
    pwm_stop="PWM stoppen",
    status_header="Status",
    status_mode="Aktueller Modus",
    status_current_pwm="Aktive PWM-Parameter",
    status_last_error="Letzter Fehler",
    status_pulse_running="Puls laeuft gerade",
    status_idle="Bereit.",
    ok_pulse_fired="Puls von {ms:.1f} ms ausgeloest.",
    ok_pwm_started="PWM gestartet: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_pwm_updated="PWM aktualisiert: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_stopped="Ausgang gestoppt, Pin auf LOW.",
    warn_hw_not_available="Hardware nicht verfuegbar (Mock-Modus aktiv).",
    err_hw_dialog_title="Hardware-Fehler",
)


_EN = Strings(
    window_title="NOTAVIS Trigger — GPIO 18",
    subtitle="External camera trigger on Raspberry Pi (hardware PWM).",
    menu_language="Language",
    lang_de="German",
    lang_en="English",
    tab_single="Single-shot",
    tab_pwm="Continuous PWM",
    single_header="Single-shot pulse",
    single_pulse_label=f"Pulse duration (ms) — {PULSE_MIN_MS:.1f} to {PULSE_MAX_MS:.0f}",
    single_fire="Fire trigger manually",
    pwm_header="Continuous PWM signal",
    pwm_freq_label=f"Frequency (Hz) — {FREQ_MIN_HZ:.0f} to {FREQ_MAX_HZ:.0f}",
    pwm_duty_label=f"Duty cycle (%) — {DUTY_MIN_PCT:.0f} to {DUTY_MAX_PCT:.0f}",
    pwm_start="Start / update PWM",
    pwm_stop="Stop PWM",
    status_header="Status",
    status_mode="Current mode",
    status_current_pwm="Active PWM parameters",
    status_last_error="Last error",
    status_pulse_running="A pulse is in flight",
    status_idle="Ready.",
    ok_pulse_fired="Fired a {ms:.1f} ms pulse.",
    ok_pwm_started="PWM started: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_pwm_updated="PWM updated: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_stopped="Output stopped, pin driven LOW.",
    warn_hw_not_available="Hardware not available (mock mode active).",
    err_hw_dialog_title="Hardware error",
)


# ----------------------------------------------------------- worker thread ---


class _SingleShotWorker(QObject):
    """Runs the blocking single-shot pulse off the UI thread."""

    finished = Signal(float)          # pulse_ms (as fired)
    failed = Signal(str)              # error message

    def __init__(self, controller: TriggerController, params: SingleShotParams) -> None:
        super().__init__()
        self._controller = controller
        self._params = params

    def run(self) -> None:
        try:
            self._controller.fire_single_shot(self._params)
            self.finished.emit(self._params.pulse_ms)
        except TriggerControllerError as exc:
            self.failed.emit(str(exc))


# ------------------------------------------------------------- main window --


class TriggerWindow(QMainWindow):
    """Top-level window with two tabs (single-shot / PWM) and a status footer."""

    def __init__(self, controller: TriggerController, strings: Strings) -> None:
        super().__init__()
        self._controller = controller
        self._strings = strings
        self._pulse_worker: _SingleShotWorker | None = None
        self._pulse_thread: QThread | None = None

        self.setWindowTitle(strings.window_title)
        self.resize(720, 520)

        # Central layout: title + tabs.
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel(strings.window_title)
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #01696F;")
        subtitle = QLabel(strings.subtitle)
        subtitle.setStyleSheet("color: #4A4842;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_single_shot_tab(), strings.tab_single)
        self._tabs.addTab(self._build_pwm_tab(), strings.tab_pwm)
        layout.addWidget(self._tabs, stretch=1)

        # Status footer.
        self._status_mode_label = QLabel()
        self._status_pwm_label = QLabel()
        self._status_error_label = QLabel()
        self._status_error_label.setStyleSheet("color: #B71C1C;")
        status_box = QGroupBox(strings.status_header)
        status_layout = QVBoxLayout(status_box)
        status_layout.addWidget(self._status_mode_label)
        status_layout.addWidget(self._status_pwm_label)
        status_layout.addWidget(self._status_error_label)
        layout.addWidget(status_box)

        self.setStatusBar(QStatusBar(self))
        if os.environ.get("VC_TRIGGER_MOCK", "0") == "1":
            self.statusBar().showMessage(strings.warn_hw_not_available)
        else:
            self.statusBar().showMessage(strings.status_idle)

        # Menu (language toggle).
        self._build_menu()

        # Periodic status refresh (1 Hz — cheap, keeps footer accurate).
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()
        self._refresh_status()

    # ---- tab: single-shot -------------------------------------------------

    def _build_single_shot_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        v.addWidget(QLabel(self._strings.single_header))

        row = QHBoxLayout()
        row.addWidget(QLabel(self._strings.single_pulse_label))
        self._pulse_spin = QDoubleSpinBox()
        self._pulse_spin.setRange(PULSE_MIN_MS, PULSE_MAX_MS)
        self._pulse_spin.setDecimals(1)
        self._pulse_spin.setSingleStep(0.1)
        self._pulse_spin.setValue(10.0)
        self._pulse_spin.setSuffix(" ms")
        row.addWidget(self._pulse_spin, stretch=1)
        v.addLayout(row)

        self._pulse_slider = QSlider(Qt.Orientation.Horizontal)
        self._pulse_slider.setRange(int(PULSE_MIN_MS * 10), int(PULSE_MAX_MS * 10))
        self._pulse_slider.setValue(int(10.0 * 10))
        self._pulse_slider.valueChanged.connect(
            lambda x: self._pulse_spin.setValue(x / 10.0)
        )
        self._pulse_spin.valueChanged.connect(
            lambda x: self._pulse_slider.setValue(int(x * 10))
        )
        v.addWidget(self._pulse_slider)

        self._fire_button = QPushButton(self._strings.single_fire)
        self._fire_button.setStyleSheet(_PRIMARY_QSS)
        self._fire_button.clicked.connect(self._on_fire)
        v.addWidget(self._fire_button)

        v.addStretch(1)
        return w

    def _on_fire(self) -> None:
        if self._pulse_thread is not None:
            return  # already firing
        try:
            params = SingleShotParams(pulse_ms=self._pulse_spin.value())
        except ValueError as exc:
            self._show_error(str(exc))
            return

        self._fire_button.setEnabled(False)
        self._pulse_thread = QThread(self)
        self._pulse_worker = _SingleShotWorker(self._controller, params)
        self._pulse_worker.moveToThread(self._pulse_thread)
        self._pulse_thread.started.connect(self._pulse_worker.run)
        self._pulse_worker.finished.connect(self._on_pulse_finished)
        self._pulse_worker.failed.connect(self._on_pulse_failed)
        self._pulse_worker.finished.connect(self._pulse_thread.quit)
        self._pulse_worker.failed.connect(self._pulse_thread.quit)
        self._pulse_thread.finished.connect(self._pulse_thread_cleanup)
        self._pulse_thread.start()

    def _on_pulse_finished(self, ms: float) -> None:
        self.statusBar().showMessage(self._strings.ok_pulse_fired.format(ms=ms), 5000)

    def _on_pulse_failed(self, msg: str) -> None:
        self._show_error(msg)

    def _pulse_thread_cleanup(self) -> None:
        if self._pulse_thread is not None:
            self._pulse_thread.deleteLater()
        if self._pulse_worker is not None:
            self._pulse_worker.deleteLater()
        self._pulse_thread = None
        self._pulse_worker = None
        self._fire_button.setEnabled(True)
        self._refresh_status()

    # ---- tab: PWM ---------------------------------------------------------

    def _build_pwm_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        v.addWidget(QLabel(self._strings.pwm_header))

        # Frequency
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel(self._strings.pwm_freq_label))
        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(FREQ_MIN_HZ, FREQ_MAX_HZ)
        self._freq_spin.setDecimals(1)
        self._freq_spin.setSingleStep(1.0)
        self._freq_spin.setValue(100.0)
        self._freq_spin.setSuffix(" Hz")
        freq_row.addWidget(self._freq_spin, stretch=1)
        v.addLayout(freq_row)
        self._freq_slider = QSlider(Qt.Orientation.Horizontal)
        self._freq_slider.setRange(int(FREQ_MIN_HZ), int(FREQ_MAX_HZ))
        self._freq_slider.setValue(100)
        self._freq_slider.valueChanged.connect(lambda x: self._freq_spin.setValue(float(x)))
        self._freq_spin.valueChanged.connect(lambda x: self._freq_slider.setValue(int(x)))
        v.addWidget(self._freq_slider)

        # Duty
        duty_row = QHBoxLayout()
        duty_row.addWidget(QLabel(self._strings.pwm_duty_label))
        self._duty_spin = QDoubleSpinBox()
        self._duty_spin.setRange(DUTY_MIN_PCT, DUTY_MAX_PCT)
        self._duty_spin.setDecimals(1)
        self._duty_spin.setSingleStep(1.0)
        self._duty_spin.setValue(50.0)
        self._duty_spin.setSuffix(" %")
        duty_row.addWidget(self._duty_spin, stretch=1)
        v.addLayout(duty_row)
        self._duty_slider = QSlider(Qt.Orientation.Horizontal)
        self._duty_slider.setRange(int(DUTY_MIN_PCT * 10), int(DUTY_MAX_PCT * 10))
        self._duty_slider.setValue(500)
        self._duty_slider.valueChanged.connect(lambda x: self._duty_spin.setValue(x / 10.0))
        self._duty_spin.valueChanged.connect(lambda x: self._duty_slider.setValue(int(x * 10)))
        v.addWidget(self._duty_slider)

        # Buttons
        row = QHBoxLayout()
        self._pwm_start_button = QPushButton(self._strings.pwm_start)
        self._pwm_start_button.setStyleSheet(_PRIMARY_QSS)
        self._pwm_start_button.clicked.connect(self._on_pwm_start)
        row.addWidget(self._pwm_start_button)
        self._pwm_stop_button = QPushButton(self._strings.pwm_stop)
        self._pwm_stop_button.setStyleSheet(_SECONDARY_QSS)
        self._pwm_stop_button.clicked.connect(self._on_pwm_stop)
        row.addWidget(self._pwm_stop_button)
        v.addLayout(row)

        v.addStretch(1)
        return w

    def _on_pwm_start(self) -> None:
        try:
            params = PwmParams(
                frequency_hz=self._freq_spin.value(),
                duty_cycle_pct=self._duty_spin.value(),
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return
        try:
            was_running = self._controller.mode == TriggerMode.PWM
            self._controller.start_pwm(params)
            template = (
                self._strings.ok_pwm_updated if was_running else self._strings.ok_pwm_started
            )
            self.statusBar().showMessage(
                template.format(hz=params.frequency_hz, duty=params.duty_cycle_pct),
                5000,
            )
            self._refresh_status()
        except TriggerControllerError as exc:
            self._show_error(str(exc))

    def _on_pwm_stop(self) -> None:
        try:
            self._controller.stop()
            self.statusBar().showMessage(self._strings.ok_stopped, 5000)
            self._refresh_status()
        except TriggerControllerError as exc:
            self._show_error(str(exc))

    # ---- status refresh ---------------------------------------------------

    def _refresh_status(self) -> None:
        s = self._strings
        mode = self._controller.mode
        self._status_mode_label.setText(f"<b>{s.status_mode}:</b> <code>{mode.value}</code>")
        pwm = self._controller.current_pwm
        if pwm is not None:
            self._status_pwm_label.setText(
                f"<b>{s.status_current_pwm}:</b> {pwm.frequency_hz:.1f} Hz, "
                f"duty {pwm.duty_cycle_pct:.1f} %"
            )
        else:
            self._status_pwm_label.setText("")
        err = self._controller.last_error
        self._status_error_label.setText(f"<b>{s.status_last_error}:</b> {err}" if err else "")

    # ---- menu -------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        lang_menu = menubar.addMenu(self._strings.menu_language)
        act_de = QAction(self._strings.lang_de, self)
        act_de.triggered.connect(lambda: self._switch_language(_DE))
        act_en = QAction(self._strings.lang_en, self)
        act_en.triggered.connect(lambda: self._switch_language(_EN))
        lang_menu.addAction(act_de)
        lang_menu.addAction(act_en)

    def _switch_language(self, strings: Strings) -> None:
        # Simplest safe path: recreate the window with the new language.
        # State (current PWM, running pulse) lives in the controller, so no data
        # is lost.
        new = TriggerWindow(self._controller, strings)
        new.show()
        self.close()

    # ---- helpers ----------------------------------------------------------

    def _show_error(self, msg: str) -> None:
        QMessageBox.critical(self, self._strings.err_hw_dialog_title, msg)
        self._refresh_status()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        try:
            self._controller.stop()
        except TriggerControllerError:
            pass
        super().closeEvent(event)


# --------------------------------------------------------------- entry point


def main() -> int:
    configure_logging()
    mock = os.environ.get("VC_TRIGGER_MOCK", "0") == "1"
    controller = get_controller(mock=mock)

    app = QApplication.instance() or QApplication(sys.argv)
    window = TriggerWindow(controller, _DE)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
