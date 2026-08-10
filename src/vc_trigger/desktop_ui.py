"""PySide6 desktop UI for the VC MIPI GPIO/PWM trigger.

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

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSlider, QSpinBox, QStackedWidget, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget,
)

from .controller import TriggerController, TriggerControllerError, get_controller
from .logging_setup import configure_logging
from .models import (
    DUTY_MAX_PCT, DUTY_MIN_PCT, EXPOSURE_MAX_US, EXPOSURE_MIN_US, FREQ_MAX_HZ,
    FREQ_MIN_HZ, GAIN_MAX, GAIN_MIN, PULSE_MAX_MS, PULSE_MIN_MS, PwmParams,
    SENSOR_TRIGGER_MODE_MAX, SENSOR_TRIGGER_MODE_MIN, SensorParams,
    SensorPixelFormat, SensorVendor, SingleShotParams, TriggerMode,
)
from .sensor_catalog_loader import CatalogEntry, SensorCatalogError
from .sensor_controller import (
    DEFAULT_SENSOR_SUBDEV,
    DiscoveryResult,
    SensorController,
    SensorControllerError,
    discover_sensor,
)
from .sensor_profiles_loader import (
    SensorProfile,
    SensorProfileError,
    UnknownSensorError,
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
    err_dialog_title: str
    # sensor tester
    top_tab_trigger: str
    top_tab_sensor: str
    sensor_header: str
    sensor_vendor_label: str
    sensor_vendor_omnivision: str
    sensor_vendor_sony: str
    sensor_trigger_mode_label: str
    sensor_trigger_mode_stream: str
    sensor_trigger_mode_ext_edge: str
    sensor_trigger_mode_ext_pulse: str
    sensor_exposure_label: str
    sensor_gain_label: str
    sensor_lanes_label: str
    sensor_lanes_note: str
    sensor_format_label: str
    sensor_read_button: str
    sensor_apply_button: str
    sensor_capture_button: str
    sensor_capture_count_label: str
    sensor_log_header: str
    sensor_save_log_button: str
    sensor_clear_log_button: str
    sensor_ok_applied: str
    sensor_ok_read: str
    sensor_ok_capture: str
    sensor_warn_mock: str


_DE = Strings(
    window_title="VC MIPI Trigger — GPIO 18",
    subtitle="Externer Kamera-Trigger fuer Vision Components MIPI-Module.",
    menu_language="Sprache", lang_de="Deutsch", lang_en="English",
    tab_single="Einzel-Puls", tab_pwm="Kontinuierliches PWM",
    single_header="Einzel-Puls (Single-Shot)",
    single_pulse_label="Pulsdauer (ms)",
    single_fire="Trigger manuell ausloesen",
    pwm_header="Kontinuierliches PWM-Signal",
    pwm_freq_label="Frequenz (Hz)", pwm_duty_label="Duty Cycle (%)",
    pwm_start="PWM starten", pwm_stop="PWM stoppen",
    status_header="Status", status_mode="Aktueller Modus",
    status_current_pwm="Aktive PWM-Parameter",
    status_last_error="Letzter Fehler",
    status_pulse_running="Puls laeuft gerade …",
    status_idle="Bereit.",
    ok_pulse_fired="Puls von {ms:.1f} ms ausgeloest.",
    ok_pwm_started="PWM gestartet: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_pwm_updated="PWM aktualisiert: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_stopped="Ausgang gestoppt, Pin auf LOW.",
    warn_hw_not_available="Hardware nicht verfuegbar (Mock-Modus aktiv).",
    err_dialog_title="Trigger-Fehler",
    top_tab_trigger="Trigger",
    top_tab_sensor="Sensor-Test",
    sensor_header="VC MIPI Sensor-Parameter",
    sensor_vendor_label="Sensor-Hersteller (Hinweis)",
    sensor_vendor_omnivision="Omnivision",
    sensor_vendor_sony="Sony",
    sensor_trigger_mode_label="Trigger-Modus",
    sensor_trigger_mode_stream="0 — Streaming (frei)",
    sensor_trigger_mode_ext_edge="1 — Extern, Flanke",
    sensor_trigger_mode_ext_pulse="2 — Extern, Pulsbreite",
    sensor_exposure_label="Belichtung (µs)",
    sensor_gain_label="Analogue Gain",
    sensor_lanes_label="MIPI-Lanes",
    sensor_lanes_note="Aenderung erfordert config.txt + Reboot.",
    sensor_format_label="Pixel-Format",
    sensor_read_button="Aktuelle Werte lesen",
    sensor_apply_button="Uebernehmen",
    sensor_capture_button="Frames aufnehmen",
    sensor_capture_count_label="Anzahl Frames",
    sensor_log_header="Log",
    sensor_save_log_button="Log speichern …",
    sensor_clear_log_button="Log leeren",
    sensor_ok_applied="Sensor-Parameter uebernommen.",
    sensor_ok_read="Sensor-Zustand gelesen: {name}.",
    sensor_ok_capture="{count} Frames nach {path} geschrieben.",
    sensor_warn_mock="Sensor im Mock-Modus (kein Board erreichbar).",
)

_EN = Strings(
    window_title="VC MIPI Trigger — GPIO 18",
    subtitle="External camera trigger for Vision Components MIPI modules.",
    menu_language="Language", lang_de="Deutsch", lang_en="English",
    tab_single="Single-shot", tab_pwm="Continuous PWM",
    single_header="Single-shot pulse",
    single_pulse_label="Pulse duration (ms)",
    single_fire="Fire trigger manually",
    pwm_header="Continuous PWM signal",
    pwm_freq_label="Frequency (Hz)", pwm_duty_label="Duty cycle (%)",
    pwm_start="Start PWM", pwm_stop="Stop PWM",
    status_header="Status", status_mode="Current mode",
    status_current_pwm="Active PWM parameters",
    status_last_error="Last error",
    status_pulse_running="A pulse is in flight …",
    status_idle="Ready.",
    ok_pulse_fired="Fired a {ms:.1f} ms pulse.",
    ok_pwm_started="PWM started: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_pwm_updated="PWM updated: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_stopped="Output stopped, pin driven LOW.",
    warn_hw_not_available="Hardware not available (mock mode active).",
    err_dialog_title="Trigger error",
    top_tab_trigger="Trigger",
    top_tab_sensor="Sensor test",
    sensor_header="VC MIPI sensor parameters",
    sensor_vendor_label="Sensor vendor (hint)",
    sensor_vendor_omnivision="Omnivision",
    sensor_vendor_sony="Sony",
    sensor_trigger_mode_label="Trigger mode",
    sensor_trigger_mode_stream="0 — Streaming (free-run)",
    sensor_trigger_mode_ext_edge="1 — External, edge",
    sensor_trigger_mode_ext_pulse="2 — External, pulse width",
    sensor_exposure_label="Exposure (µs)",
    sensor_gain_label="Analogue gain",
    sensor_lanes_label="MIPI lanes",
    sensor_lanes_note="Changing requires editing config.txt and a reboot.",
    sensor_format_label="Pixel format",
    sensor_read_button="Read current",
    sensor_apply_button="Apply",
    sensor_capture_button="Capture frames",
    sensor_capture_count_label="Frame count",
    sensor_log_header="Log",
    sensor_save_log_button="Save log …",
    sensor_clear_log_button="Clear log",
    sensor_ok_applied="Sensor parameters applied.",
    sensor_ok_read="Sensor state read: {name}.",
    sensor_ok_capture="Wrote {count} frames to {path}.",
    sensor_warn_mock="Sensor in mock mode (no board reachable).",
)


def _make_slider_row(
    parent_layout: QVBoxLayout, label: QLabel,
    minimum: float, maximum: float, initial: float,
    suffix: str, decimals: int, scale: int, step: float,
) -> tuple[QSlider, QDoubleSpinBox]:
    """Build a horizontal row of ``[label] [slider] [spinbox suffix]``.

    ``QSlider`` is integer-only; ``scale`` factors the resolution.
    Returns the two live widgets so callers can read their values.
    """
    row = QHBoxLayout()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimum(int(round(minimum * scale)))
    slider.setMaximum(int(round(maximum * scale)))
    slider.setValue(int(round(initial * scale)))
    spin = QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setMinimum(minimum)
    spin.setMaximum(maximum)
    spin.setSingleStep(step)
    spin.setValue(initial)
    spin.setSuffix(suffix)
    # Two-way wire without feedback loops (blockSignals guards).
    def _slider_changed(v: int) -> None:
        spin.blockSignals(True)
        spin.setValue(v / scale)
        spin.blockSignals(False)
    def _spin_changed(v: float) -> None:
        slider.blockSignals(True)
        slider.setValue(int(round(v * scale)))
        slider.blockSignals(False)
    slider.valueChanged.connect(_slider_changed)
    spin.valueChanged.connect(_spin_changed)
    row.addWidget(label)
    row.addWidget(slider, stretch=1)
    row.addWidget(spin)
    parent_layout.addLayout(row)
    return slider, spin


class _SingleShotWorker(QObject):
    """Runs :meth:`TriggerController.fire_single_shot` off the GUI thread."""

    finished = Signal(float)  # emitted with pulse_ms on success
    failed = Signal(str)      # emitted with error message

    def __init__(self, controller: TriggerController, params: SingleShotParams) -> None:
        super().__init__()
        self._controller = controller
        self._params = params

    def run(self) -> None:
        _LOG.info("firing single-shot pulse: %.2f ms", self._params.pulse_ms)
        try:
            self._controller.fire_single_shot(self._params)
        except TriggerControllerError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            _LOG.exception("unexpected error in single-shot worker")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(self._params.pulse_ms)


class TriggerMainWindow(QMainWindow):
    """Main window of the desktop trigger UI.

    The ``controller`` argument is injected so tests can pass a mock instance.
    """

    _POLL_INTERVAL_MS = 200

    def __init__(
        self,
        controller: TriggerController | None = None,
        *,
        sensor_controller: SensorController | None = None,
        strings: Strings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller or get_controller(
            mock=os.environ.get("VC_TRIGGER_MOCK", "0") == "1"
        )
        mock_env = os.environ.get("VC_TRIGGER_MOCK", "0") == "1"
        self._sensor_profile: SensorProfile | None = None
        self._sensor_catalog: CatalogEntry | None = None
        self._sensor_detected_name: str | None = None
        self._sensor_detect_error: str | None = None
        if sensor_controller is None:
            if not mock_env:
                try:
                    result: DiscoveryResult = discover_sensor()
                    self._sensor_detected_name = result.sensor_name
                    self._sensor_profile = result.profile
                    self._sensor_catalog = result.catalog
                    if result.is_unknown:
                        self._sensor_detect_error = (
                            f"Sensor {result.sensor_name!r} nicht im Katalog. "
                            f"Ergaenze <sensor_name>.yaml unter "
                            f"src/vc_trigger/sensor_profiles/catalog/."
                        )
                        _LOG.warning(
                            "sensor %s: neither live profile nor catalog entry",
                            result.sensor_name,
                        )
                except (SensorControllerError, SensorProfileError, SensorCatalogError) as exc:
                    self._sensor_detect_error = str(exc)
                    _LOG.warning("sensor auto-detect failed: %s", exc)
            self._sensor_controller = SensorController(
                mock=mock_env, profile=self._sensor_profile,
            )
        else:
            self._sensor_controller = sensor_controller
            self._sensor_profile = sensor_controller.profile
        self._strings = strings or _DE
        self._worker_thread: QThread | None = None
        self._active_worker: _SingleShotWorker | None = None
        self._build_ui()
        self._retranslate()
        self._refresh_status()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_status)
        self._poll_timer.start()

    # ---------- construction -----------------------------------------------

    def _build_ui(self) -> None:
        self.setMinimumSize(720, 560)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._subtitle_label = QLabel()
        self._subtitle_label.setStyleSheet("color: #7A7974;")
        layout.addWidget(self._subtitle_label)

        # Top-level tab widget: Trigger | Sensor test
        self._top_tabs = QTabWidget()
        self._top_tabs.addTab(self._build_trigger_page(), "")
        self._top_tabs.addTab(self._build_sensor_page(), "")
        layout.addWidget(self._top_tabs, stretch=1)

        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        if self._controller_is_mock():
            self._status_bar.setStyleSheet("color: #964219;")  # warning

        self._menu_lang = self.menuBar().addMenu("")
        self._action_de = QAction(self)
        self._action_en = QAction(self)
        self._action_de.setCheckable(True)
        self._action_en.setCheckable(True)
        self._action_de.setChecked(True)
        self._action_de.triggered.connect(lambda: self._set_language(_DE))
        self._action_en.triggered.connect(lambda: self._set_language(_EN))
        self._menu_lang.addAction(self._action_de)
        self._menu_lang.addAction(self._action_en)

    def _build_trigger_page(self) -> QWidget:
        """Existing trigger UI wrapped as the first top-level tab."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self._mode_combo = QComboBox()
        layout.addWidget(self._mode_combo)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_single_page())
        self._pages.addWidget(self._build_pwm_page())
        layout.addWidget(self._pages, stretch=1)
        self._mode_combo.currentIndexChanged.connect(self._pages.setCurrentIndex)

        self._status_group = QGroupBox()
        status_layout = QVBoxLayout(self._status_group)
        self._status_mode_label = QLabel()
        self._status_pwm_label = QLabel()
        self._status_error_label = QLabel()
        self._status_error_label.setStyleSheet("color: #A12C7B;")
        self._status_pulse_label = QLabel()
        self._status_pulse_label.setStyleSheet("color: #01696F;")
        for w in (self._status_mode_label, self._status_pwm_label,
                  self._status_pulse_label, self._status_error_label):
            status_layout.addWidget(w)
        layout.addWidget(self._status_group)
        return page

    def _build_sensor_page(self) -> QWidget:
        """Second top-level tab: read/write VC MIPI sensor parameters via V4L2."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self._sensor_header = QLabel()
        self._sensor_header.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self._sensor_header)

        # Read-only detected-sensor label (populated by _apply_sensor_profile).
        # Colored teal for live-verified profiles, gold for catalog-only.
        self._sensor_detected_label = QLabel()
        self._sensor_detected_label.setStyleSheet(
            "color: #01696F; font-weight: 600;"
        )
        self._sensor_detected_label.setVisible(False)
        self._sensor_detected_label.setWordWrap(True)
        layout.addWidget(self._sensor_detected_label)

        # Warning banner: sensor recognized via catalog but not live-verified.
        # Gold (#D19900) per NOTAVIS palette — distinct from error (magenta).
        self._sensor_catalog_label = QLabel()
        self._sensor_catalog_label.setStyleSheet(
            "color: #964219; font-weight: 600;"
        )
        self._sensor_catalog_label.setWordWrap(True)
        self._sensor_catalog_label.setVisible(False)
        layout.addWidget(self._sensor_catalog_label)

        # Error banner shown when auto-detection fails.
        self._sensor_error_label = QLabel()
        self._sensor_error_label.setStyleSheet(
            "color: #A12C7B; font-weight: 600;"
        )
        self._sensor_error_label.setWordWrap(True)
        self._sensor_error_label.setVisible(False)
        layout.addWidget(self._sensor_error_label)

        # Vendor radio row
        vendor_row = QHBoxLayout()
        self._sensor_vendor_label = QLabel()
        self._sensor_vendor_omnivision_radio = QRadioButton()
        self._sensor_vendor_omnivision_radio.setChecked(True)
        self._sensor_vendor_sony_radio = QRadioButton()
        vendor_row.addWidget(self._sensor_vendor_label)
        vendor_row.addWidget(self._sensor_vendor_omnivision_radio)
        vendor_row.addWidget(self._sensor_vendor_sony_radio)
        vendor_row.addStretch(1)
        layout.addLayout(vendor_row)

        # Trigger-mode combo
        tm_row = QHBoxLayout()
        self._sensor_trigger_mode_label_widget = QLabel()
        self._sensor_trigger_mode_combo = QComboBox()
        tm_row.addWidget(self._sensor_trigger_mode_label_widget)
        tm_row.addWidget(self._sensor_trigger_mode_combo, stretch=1)
        layout.addLayout(tm_row)

        # Lanes combo (informational)
        lanes_row = QHBoxLayout()
        self._sensor_lanes_label_widget = QLabel()
        self._sensor_lanes_combo = QComboBox()
        for lanes in ("1", "2", "4"):
            self._sensor_lanes_combo.addItem(lanes)
        self._sensor_lanes_combo.setCurrentIndex(1)
        self._sensor_lanes_note_label = QLabel()
        self._sensor_lanes_note_label.setStyleSheet("color: #7A7974;")
        lanes_row.addWidget(self._sensor_lanes_label_widget)
        lanes_row.addWidget(self._sensor_lanes_combo)
        lanes_row.addWidget(self._sensor_lanes_note_label, stretch=1)
        layout.addLayout(lanes_row)

        # Exposure spinbox
        exp_row = QHBoxLayout()
        self._sensor_exposure_label_widget = QLabel()
        self._sensor_exposure_spin = QSpinBox()
        self._sensor_exposure_spin.setRange(EXPOSURE_MIN_US, EXPOSURE_MAX_US)
        self._sensor_exposure_spin.setValue(10_000)
        self._sensor_exposure_spin.setSuffix(" us")
        self._sensor_exposure_spin.setSingleStep(100)
        exp_row.addWidget(self._sensor_exposure_label_widget)
        exp_row.addWidget(self._sensor_exposure_spin, stretch=1)
        layout.addLayout(exp_row)

        # Gain spinbox
        gain_row = QHBoxLayout()
        self._sensor_gain_label_widget = QLabel()
        self._sensor_gain_spin = QSpinBox()
        self._sensor_gain_spin.setRange(GAIN_MIN, GAIN_MAX)
        self._sensor_gain_spin.setValue(0)
        self._sensor_gain_spin.setSingleStep(50)
        gain_row.addWidget(self._sensor_gain_label_widget)
        gain_row.addWidget(self._sensor_gain_spin, stretch=1)
        layout.addLayout(gain_row)

        # Pixel format combo — populated dynamically from the sensor profile
        # in :meth:`_populate_pixel_format_combo`. Falls back to RAW08/RAW10
        # when no profile is available (mock mode or unknown sensor).
        fmt_row = QHBoxLayout()
        self._sensor_format_label_widget = QLabel()
        self._sensor_format_combo = QComboBox()
        fmt_row.addWidget(self._sensor_format_label_widget)
        fmt_row.addWidget(self._sensor_format_combo, stretch=1)
        layout.addLayout(fmt_row)
        self._populate_pixel_format_combo()

        # Capture count + action buttons
        cap_row = QHBoxLayout()
        self._sensor_capture_count_label_widget = QLabel()
        self._sensor_capture_count_spin = QSpinBox()
        self._sensor_capture_count_spin.setRange(1, 1_000)
        self._sensor_capture_count_spin.setValue(30)
        cap_row.addWidget(self._sensor_capture_count_label_widget)
        cap_row.addWidget(self._sensor_capture_count_spin)
        cap_row.addStretch(1)
        layout.addLayout(cap_row)

        button_row = QHBoxLayout()
        self._sensor_read_button = QPushButton()
        self._sensor_read_button.setStyleSheet(_SECONDARY_QSS)
        self._sensor_read_button.clicked.connect(self._on_sensor_read)
        self._sensor_apply_button = QPushButton()
        self._sensor_apply_button.setStyleSheet(_PRIMARY_QSS)
        self._sensor_apply_button.clicked.connect(self._on_sensor_apply)
        self._sensor_capture_button = QPushButton()
        self._sensor_capture_button.setStyleSheet(_SECONDARY_QSS)
        self._sensor_capture_button.clicked.connect(self._on_sensor_capture)
        button_row.addWidget(self._sensor_read_button)
        button_row.addWidget(self._sensor_apply_button)
        button_row.addWidget(self._sensor_capture_button)
        layout.addLayout(button_row)

        # Log view
        self._sensor_log_header_widget = QLabel()
        self._sensor_log_header_widget.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._sensor_log_header_widget)
        self._sensor_log_view = QPlainTextEdit()
        self._sensor_log_view.setReadOnly(True)
        self._sensor_log_view.setStyleSheet(
            "font-family: 'DejaVu Sans Mono', 'Courier New', monospace; font-size: 11px;"
        )
        layout.addWidget(self._sensor_log_view, stretch=1)

        log_button_row = QHBoxLayout()
        self._sensor_save_log_button = QPushButton()
        self._sensor_save_log_button.setStyleSheet(_SECONDARY_QSS)
        self._sensor_save_log_button.clicked.connect(self._on_sensor_save_log)
        self._sensor_clear_log_button = QPushButton()
        self._sensor_clear_log_button.setStyleSheet(_SECONDARY_QSS)
        self._sensor_clear_log_button.clicked.connect(
            lambda: self._sensor_log_view.clear()
        )
        log_button_row.addWidget(self._sensor_save_log_button)
        log_button_row.addWidget(self._sensor_clear_log_button)
        log_button_row.addStretch(1)
        layout.addLayout(log_button_row)

        self._apply_sensor_profile()
        return page

    def _populate_pixel_format_combo(self) -> None:
        """Fill the pixel-format combo from the active source.

        Priority:

        1. Live profile (``self._sensor_profile``) — exact fourcc + labels.
        2. Catalog entry (``self._sensor_catalog``) — declared format IDs
           only; fourcc is not populated because catalog data is not
           live-verified.
        3. Legacy hard-coded RAW08/RAW10 fallback.
        """
        self._sensor_format_combo.clear()
        profile = self._sensor_profile
        if profile is not None:
            for entry in profile.pixel_formats:
                self._sensor_format_combo.addItem(
                    entry.label, userData=entry.id.value,
                )
            default_val = profile.default_pixel_format.value
            idx = self._sensor_format_combo.findData(default_val)
            if idx >= 0:
                self._sensor_format_combo.setCurrentIndex(idx)
            return

        catalog = self._sensor_catalog
        if catalog is not None and catalog.modes.format_options:
            for fmt_id in catalog.modes.format_options:
                try:
                    enum_val = SensorPixelFormat(fmt_id)
                except ValueError:
                    continue  # skip unknown IDs (forward-compat)
                self._sensor_format_combo.addItem(fmt_id, userData=enum_val.value)
            if self._sensor_format_combo.count() > 0:
                # Prefer RAW10 if the catalog lists it, else first entry.
                idx = self._sensor_format_combo.findData(
                    SensorPixelFormat.RAW10.value,
                )
                self._sensor_format_combo.setCurrentIndex(idx if idx >= 0 else 0)
                return

        # Legacy fallback: two hard-coded entries.
        self._sensor_format_combo.addItem(
            "RAW08", userData=SensorPixelFormat.RAW08.value,
        )
        self._sensor_format_combo.addItem(
            "RAW10", userData=SensorPixelFormat.RAW10.value,
        )
        self._sensor_format_combo.setCurrentIndex(1)  # RAW10 default

    def _apply_sensor_profile(self) -> None:
        """Update read-only labels and vendor radios from detection state.

        Three visual states:

        * live-verified profile → teal check-mark label
        * catalog-only entry    → warm-orange "recognized, not verified"
        * unknown / error       → magenta error banner
        """
        profile = self._sensor_profile
        catalog = self._sensor_catalog

        if profile is not None:
            self._sensor_detected_label.setText(
                f"✓ {profile.display_name}  —  {profile.native_width}×"
                f"{profile.native_height}, mediabus {profile.mediabus_code}"
            )
            self._sensor_detected_label.setVisible(True)
            self._sensor_catalog_label.setVisible(False)
            self._sensor_error_label.setVisible(False)
            if profile.vendor == SensorVendor.SONY.value:
                self._sensor_vendor_sony_radio.setChecked(True)
            elif profile.vendor == SensorVendor.OMNIVISION.value:
                self._sensor_vendor_omnivision_radio.setChecked(True)
            return

        if catalog is not None:
            self._sensor_detected_label.setVisible(False)
            self._sensor_error_label.setVisible(False)
            self._sensor_catalog_label.setText(
                f"◐ Sensor erkannt: {catalog.display_name} (Katalog) — "
                f"{catalog.native.width}×{catalog.native.height}, "
                f"{catalog.shutter} shutter. "
                f"Kein Live-Profile — Werte sind nicht verifiziert. "
                f"Ergaenze {catalog.sensor_name}.yaml unter "
                f"src/vc_trigger/sensor_profiles/."
            )
            self._sensor_catalog_label.setVisible(True)
            if catalog.vendor.lower() == SensorVendor.SONY.value:
                self._sensor_vendor_sony_radio.setChecked(True)
            elif catalog.vendor.lower() == SensorVendor.OMNIVISION.value:
                self._sensor_vendor_omnivision_radio.setChecked(True)
            return

        if self._sensor_detect_error:
            self._sensor_detected_label.setVisible(False)
            self._sensor_catalog_label.setVisible(False)
            self._sensor_error_label.setText(
                "⚠ Kein Sensor-Profil geladen.\n"
                f"Detection: {self._sensor_detect_error}"
            )
            self._sensor_error_label.setVisible(True)

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self._single_header = QLabel()
        self._single_header.setStyleSheet("font-size: 16px; font-weight: 600;")
        page_layout.addWidget(self._single_header)
        self._single_pulse_label = QLabel()
        self._single_pulse_slider, self._single_pulse_spin = _make_slider_row(
            page_layout, self._single_pulse_label,
            PULSE_MIN_MS, PULSE_MAX_MS, 10.0, " ms",
            decimals=1, scale=10, step=0.1,
        )
        self._single_fire_button = QPushButton()
        self._single_fire_button.setStyleSheet(_PRIMARY_QSS)
        self._single_fire_button.clicked.connect(self._on_fire_single_shot)
        page_layout.addWidget(self._single_fire_button)
        page_layout.addStretch(1)
        return page

    def _build_pwm_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self._pwm_header = QLabel()
        self._pwm_header.setStyleSheet("font-size: 16px; font-weight: 600;")
        page_layout.addWidget(self._pwm_header)
        self._pwm_freq_label = QLabel()
        self._pwm_freq_slider, self._pwm_freq_spin = _make_slider_row(
            page_layout, self._pwm_freq_label,
            FREQ_MIN_HZ, FREQ_MAX_HZ, 100.0, " Hz",
            decimals=1, scale=1, step=1.0,
        )
        self._pwm_duty_label = QLabel()
        self._pwm_duty_slider, self._pwm_duty_spin = _make_slider_row(
            page_layout, self._pwm_duty_label,
            DUTY_MIN_PCT, DUTY_MAX_PCT, 50.0, " %",
            decimals=1, scale=1, step=1.0,
        )
        button_row = QHBoxLayout()
        self._pwm_start_button = QPushButton()
        self._pwm_start_button.setStyleSheet(_PRIMARY_QSS)
        self._pwm_stop_button = QPushButton()
        self._pwm_stop_button.setStyleSheet(_SECONDARY_QSS)
        self._pwm_start_button.clicked.connect(self._on_start_pwm)
        self._pwm_stop_button.clicked.connect(self._on_stop_pwm)
        button_row.addWidget(self._pwm_start_button)
        button_row.addWidget(self._pwm_stop_button)
        page_layout.addLayout(button_row)
        page_layout.addStretch(1)
        return page

    # ---------- language ---------------------------------------------------

    def _set_language(self, strings: Strings) -> None:
        self._strings = strings
        is_de = strings is _DE
        self._action_de.setChecked(is_de)
        self._action_en.setChecked(not is_de)
        self._retranslate()

    def _retranslate(self) -> None:
        s = self._strings
        self.setWindowTitle(s.window_title)
        self._subtitle_label.setText(s.subtitle)
        self._top_tabs.setTabText(0, s.top_tab_trigger)
        self._top_tabs.setTabText(1, s.top_tab_sensor)
        current_idx = self._mode_combo.currentIndex()
        self._mode_combo.blockSignals(True)
        self._mode_combo.clear()
        self._mode_combo.addItems([s.tab_single, s.tab_pwm])
        self._mode_combo.setCurrentIndex(max(0, current_idx))
        self._mode_combo.blockSignals(False)
        self._single_header.setText(s.single_header)
        self._single_pulse_label.setText(s.single_pulse_label)
        self._single_fire_button.setText(s.single_fire)
        self._pwm_header.setText(s.pwm_header)
        self._pwm_freq_label.setText(s.pwm_freq_label)
        self._pwm_duty_label.setText(s.pwm_duty_label)
        self._pwm_start_button.setText(s.pwm_start)
        self._pwm_stop_button.setText(s.pwm_stop)
        self._status_group.setTitle(s.status_header)
        self._menu_lang.setTitle(s.menu_language)
        self._action_de.setText(s.lang_de)
        self._action_en.setText(s.lang_en)
        # sensor tab
        self._sensor_header.setText(s.sensor_header)
        self._sensor_vendor_label.setText(s.sensor_vendor_label)
        self._sensor_vendor_omnivision_radio.setText(s.sensor_vendor_omnivision)
        self._sensor_vendor_sony_radio.setText(s.sensor_vendor_sony)
        self._sensor_trigger_mode_label_widget.setText(s.sensor_trigger_mode_label)
        tm_idx = self._sensor_trigger_mode_combo.currentIndex()
        self._sensor_trigger_mode_combo.blockSignals(True)
        self._sensor_trigger_mode_combo.clear()
        self._sensor_trigger_mode_combo.addItem(s.sensor_trigger_mode_stream, userData=0)
        self._sensor_trigger_mode_combo.addItem(s.sensor_trigger_mode_ext_edge, userData=1)
        self._sensor_trigger_mode_combo.addItem(s.sensor_trigger_mode_ext_pulse, userData=2)
        self._sensor_trigger_mode_combo.setCurrentIndex(max(0, tm_idx))
        self._sensor_trigger_mode_combo.blockSignals(False)
        self._sensor_lanes_label_widget.setText(s.sensor_lanes_label)
        self._sensor_lanes_note_label.setText(s.sensor_lanes_note)
        self._sensor_exposure_label_widget.setText(s.sensor_exposure_label)
        self._sensor_gain_label_widget.setText(s.sensor_gain_label)
        self._sensor_format_label_widget.setText(s.sensor_format_label)
        self._sensor_capture_count_label_widget.setText(s.sensor_capture_count_label)
        self._sensor_read_button.setText(s.sensor_read_button)
        self._sensor_apply_button.setText(s.sensor_apply_button)
        self._sensor_capture_button.setText(s.sensor_capture_button)
        self._sensor_log_header_widget.setText(s.sensor_log_header)
        self._sensor_save_log_button.setText(s.sensor_save_log_button)
        self._sensor_clear_log_button.setText(s.sensor_clear_log_button)
        self._refresh_status()
        if self._controller_is_mock():
            self._status_bar.showMessage(s.warn_hw_not_available)
        else:
            self._status_bar.showMessage(s.status_idle, 2000)

    # ---------- controller wiring ------------------------------------------

    def _controller_is_mock(self) -> bool:
        return bool(getattr(self._controller, "_mock", False))

    def _on_fire_single_shot(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        try:
            params = SingleShotParams(pulse_ms=self._single_pulse_spin.value())
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._single_fire_button.setEnabled(False)
        # Hold the worker + thread as instance attributes so Python's garbage
        # collector does not reap them before the thread has actually run.
        # ``QObject.moveToThread`` alone does not keep a Python-side reference.
        self._worker_thread = QThread(self)
        self._active_worker = _SingleShotWorker(self._controller, params)
        self._active_worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._active_worker.run)
        self._active_worker.finished.connect(self._on_single_shot_done)
        self._active_worker.failed.connect(self._on_single_shot_failed)
        self._active_worker.finished.connect(self._worker_thread.quit)
        self._active_worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._clear_worker_thread)
        self._worker_thread.start()

    def _clear_worker_thread(self) -> None:
        self._worker_thread = None
        self._active_worker = None
        self._single_fire_button.setEnabled(True)

    def _on_single_shot_done(self, pulse_ms: float) -> None:
        self._status_bar.showMessage(
            self._strings.ok_pulse_fired.format(ms=pulse_ms), 4000
        )

    def _on_single_shot_failed(self, message: str) -> None:
        self._show_error(message)

    def _on_start_pwm(self) -> None:
        try:
            params = PwmParams(
                frequency_hz=self._pwm_freq_spin.value(),
                duty_cycle_pct=self._pwm_duty_spin.value(),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        was_running = self._controller.mode == TriggerMode.PWM
        try:
            self._controller.start_pwm(params)
        except TriggerControllerError as exc:
            self._show_error(str(exc))
            return
        template = (
            self._strings.ok_pwm_updated if was_running else self._strings.ok_pwm_started
        )
        self._status_bar.showMessage(
            template.format(hz=params.frequency_hz, duty=params.duty_cycle_pct), 4000,
        )

    def _on_stop_pwm(self) -> None:
        try:
            self._controller.stop()
        except TriggerControllerError as exc:
            self._show_error(str(exc))
            return
        self._status_bar.showMessage(self._strings.ok_stopped, 4000)

    # ---------- status refresh --------------------------------------------

    def _refresh_status(self) -> None:
        s = self._strings
        mode = self._controller.mode
        self._status_mode_label.setText(f"{s.status_mode}: {mode.value}")

        pwm = self._controller.current_pwm
        if pwm is not None:
            self._status_pwm_label.setText(
                f"{s.status_current_pwm}: {pwm.frequency_hz:.1f} Hz, "
                f"duty {pwm.duty_cycle_pct:.1f} %"
            )
            self._status_pwm_label.setVisible(True)
        else:
            self._status_pwm_label.setVisible(False)

        self._status_pulse_label.setText(s.status_pulse_running)
        self._status_pulse_label.setVisible(self._controller.pulse_in_flight)

        err = self._controller.last_error
        if err:
            self._status_error_label.setText(f"{s.status_last_error}: {err}")
            self._status_error_label.setVisible(True)
        else:
            self._status_error_label.setVisible(False)

    # ---------- sensor tab slots ------------------------------------------

    def _current_sensor_params(self) -> SensorParams:
        vendor = (SensorVendor.SONY if self._sensor_vendor_sony_radio.isChecked()
                  else SensorVendor.OMNIVISION)
        tm = self._sensor_trigger_mode_combo.currentData()
        if tm is None:
            tm = 0
        fmt_data = self._sensor_format_combo.currentData()
        pixel_format = (SensorPixelFormat(fmt_data)
                        if fmt_data else SensorPixelFormat.RAW10)
        return SensorParams(
            exposure_us=int(self._sensor_exposure_spin.value()),
            gain=int(self._sensor_gain_spin.value()),
            trigger_mode=int(tm),
            pixel_format=pixel_format,
            vendor=vendor,
        )

    def _sensor_log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._sensor_log_view.appendPlainText(f"[{stamp}] {line}")

    def _on_sensor_read(self) -> None:
        try:
            snap = self._sensor_controller.read()
        except SensorControllerError as exc:
            self._sensor_log(f"read failed: {exc}")
            self._show_error(str(exc))
            return
        self._sensor_log(
            f"read: name={snap.sensor_name} exposure={snap.exposure_us}us "
            f"gain={snap.gain} trigger_mode={snap.trigger_mode} "
            f"pixel_format={snap.pixel_format.value if snap.pixel_format else '?'}"
        )
        # Reflect readback in the widgets
        self._sensor_exposure_spin.setValue(snap.exposure_us)
        self._sensor_gain_spin.setValue(snap.gain)
        for idx in range(self._sensor_trigger_mode_combo.count()):
            if self._sensor_trigger_mode_combo.itemData(idx) == snap.trigger_mode:
                self._sensor_trigger_mode_combo.setCurrentIndex(idx)
                break
        if snap.pixel_format is not None:
            for idx in range(self._sensor_format_combo.count()):
                if self._sensor_format_combo.itemData(idx) == snap.pixel_format.value:
                    self._sensor_format_combo.setCurrentIndex(idx)
                    break
        self._status_bar.showMessage(
            self._strings.sensor_ok_read.format(name=snap.sensor_name), 4000
        )

    def _on_sensor_apply(self) -> None:
        try:
            params = self._current_sensor_params()
        except Exception as exc:
            self._show_error(str(exc))
            return
        try:
            self._sensor_controller.apply(params)
        except SensorControllerError as exc:
            self._sensor_log(f"apply failed: {exc}")
            self._show_error(str(exc))
            return
        self._sensor_log(
            f"apply: exposure={params.exposure_us}us gain={params.gain} "
            f"trigger_mode={params.trigger_mode} pixel_format={params.pixel_format.value}"
        )
        self._status_bar.showMessage(self._strings.sensor_ok_applied, 4000)

    def _on_sensor_capture(self) -> None:
        try:
            params = self._current_sensor_params()
        except Exception as exc:
            self._show_error(str(exc))
            return
        count = int(self._sensor_capture_count_spin.value())
        out_dir = Path.home() / "vc-trigger-logs"
        try:
            target = self._sensor_controller.capture_frames(
                count=count, output_dir=out_dir,
                pixel_format=params.pixel_format,
            )
        except (SensorControllerError, ValueError) as exc:
            self._sensor_log(f"capture failed: {exc}")
            self._show_error(str(exc))
            return
        self._sensor_log(f"capture: {count} frames -> {target}")
        self._status_bar.showMessage(
            self._strings.sensor_ok_capture.format(count=count, path=str(target)),
            4000,
        )

    def _on_sensor_save_log(self) -> None:
        default_dir = Path.home() / "vc-trigger-logs"
        default_dir.mkdir(parents=True, exist_ok=True)
        default_name = default_dir / f"sensor-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
        target, _ = QFileDialog.getSaveFileName(
            self, self._strings.sensor_save_log_button, str(default_name),
        )
        if not target:
            return
        Path(target).write_text(self._sensor_log_view.toPlainText(), encoding="utf-8")
        self._sensor_log(f"log saved: {target}")

    # ---------- teardown ---------------------------------------------------

    def _show_error(self, message: str) -> None:
        _LOG.error("desktop UI reported error: %s", message)
        QMessageBox.warning(
            self, self._strings.err_dialog_title, message,
            QMessageBox.StandardButton.Ok,
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        self._poll_timer.stop()
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
        try:
            self._controller.shutdown()
        except Exception:
            _LOG.exception("error while shutting down controller on window close")
        super().closeEvent(event)


def build_app(argv: list[str] | None = None) -> tuple[QApplication, TriggerMainWindow]:
    """Construct the ``QApplication`` and main window without calling ``exec()``.

    Split out so tests can drive the widget tree without entering the event loop.
    """
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("notavis-mipi-trigger")
    app.setOrganizationName("NOTAVIS GmbH")
    window = TriggerMainWindow()
    return app, window


def main() -> int:
    configure_logging()
    app, window = build_app()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
