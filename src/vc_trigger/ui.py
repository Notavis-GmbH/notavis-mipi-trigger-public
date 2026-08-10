"""Streamlit UI for the GPIO/PWM camera trigger.

Run with:

    streamlit run src/vc_trigger/ui.py --server.address 0.0.0.0 --server.port 8501

Every hardware action requires an explicit button click; slider changes on
their own never touch the pin. A DE/EN language toggle sits in the sidebar,
default is German.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import streamlit as st

from vc_trigger.controller import (
    TriggerController,
    TriggerControllerError,
    get_controller,
)
from vc_trigger.logging_setup import configure_logging
from vc_trigger.models import (
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

# ------------------------------------------------------------------ language --


@dataclass(frozen=True)
class Strings:
    title: str
    subtitle: str
    sidebar_language: str
    sidebar_mode: str
    mode_single: str
    mode_pwm: str
    single_header: str
    single_pulse_label: str
    single_pulse_help: str
    single_apply: str
    single_fire: str
    pwm_header: str
    pwm_freq_label: str
    pwm_freq_help: str
    pwm_duty_label: str
    pwm_duty_help: str
    pwm_start: str
    pwm_stop: str
    status_header: str
    status_mode: str
    status_current_pwm: str
    status_last_error: str
    status_pulse_running: str
    ok_pulse_fired: str
    ok_pwm_started: str
    ok_pwm_updated: str
    ok_stopped: str
    warn_hw_not_available: str


_DE = Strings(
    title="NOTAVIS Trigger — GPIO 18",
    subtitle="Externer Kamera-Trigger auf Raspberry Pi (Hardware-PWM).",
    sidebar_language="Sprache",
    sidebar_mode="Modus",
    mode_single="Einzel-Puls (Single-Shot)",
    mode_pwm="Kontinuierliches PWM-Signal",
    single_header="Einzel-Puls",
    single_pulse_label="Pulsdauer (ms)",
    single_pulse_help=f"Bereich {PULSE_MIN_MS:.1f} bis {PULSE_MAX_MS:.0f} ms.",
    single_apply="Parameter uebernehmen",
    single_fire="Trigger manuell ausloesen",
    pwm_header="Kontinuierliches PWM",
    pwm_freq_label="Frequenz (Hz)",
    pwm_freq_help=f"Bereich {FREQ_MIN_HZ:.0f} bis {FREQ_MAX_HZ:.0f} Hz.",
    pwm_duty_label="Duty Cycle (%)",
    pwm_duty_help=f"Bereich {DUTY_MIN_PCT:.0f} bis {DUTY_MAX_PCT:.0f} %.",
    pwm_start="PWM starten",
    pwm_stop="PWM stoppen",
    status_header="Status",
    status_mode="Aktueller Modus",
    status_current_pwm="Aktive PWM-Parameter",
    status_last_error="Letzter Fehler",
    status_pulse_running="Puls laeuft gerade",
    ok_pulse_fired="Puls von {ms:.1f} ms ausgeloest.",
    ok_pwm_started="PWM gestartet: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_pwm_updated="PWM aktualisiert: {hz:.1f} Hz, Duty {duty:.1f} %.",
    ok_stopped="Ausgang gestoppt, Pin auf LOW.",
    warn_hw_not_available="Hardware nicht verfuegbar (Mock-Modus aktiv).",
)


_EN = Strings(
    title="NOTAVIS Trigger — GPIO 18",
    subtitle="External camera trigger on Raspberry Pi (hardware PWM).",
    sidebar_language="Language",
    sidebar_mode="Mode",
    mode_single="Single-shot pulse",
    mode_pwm="Continuous PWM signal",
    single_header="Single-shot pulse",
    single_pulse_label="Pulse duration (ms)",
    single_pulse_help=f"Range {PULSE_MIN_MS:.1f} to {PULSE_MAX_MS:.0f} ms.",
    single_apply="Apply parameters",
    single_fire="Fire trigger manually",
    pwm_header="Continuous PWM",
    pwm_freq_label="Frequency (Hz)",
    pwm_freq_help=f"Range {FREQ_MIN_HZ:.0f} to {FREQ_MAX_HZ:.0f} Hz.",
    pwm_duty_label="Duty cycle (%)",
    pwm_duty_help=f"Range {DUTY_MIN_PCT:.0f} to {DUTY_MAX_PCT:.0f} %.",
    pwm_start="Start PWM",
    pwm_stop="Stop PWM",
    status_header="Status",
    status_mode="Current mode",
    status_current_pwm="Active PWM parameters",
    status_last_error="Last error",
    status_pulse_running="A pulse is in flight",
    ok_pulse_fired="Fired a {ms:.1f} ms pulse.",
    ok_pwm_started="PWM started: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_pwm_updated="PWM updated: {hz:.1f} Hz, duty {duty:.1f} %.",
    ok_stopped="Output stopped, pin driven LOW.",
    warn_hw_not_available="Hardware not available (mock mode active).",
)


_LANG_MAP = {"Deutsch / German": _DE, "English / Englisch": _EN}


def _controller() -> TriggerController:
    # Mock mode when the app is developed off-board (e.g. on a laptop).
    mock = os.environ.get("VC_TRIGGER_MOCK", "0") == "1"
    return get_controller(mock=mock)


def _render(strings: Strings) -> None:
    st.title(strings.title)
    st.caption(strings.subtitle)

    controller = _controller()

    with st.sidebar:
        mode_label = st.radio(
            strings.sidebar_mode,
            options=[strings.mode_single, strings.mode_pwm],
            index=0,
        )

    if mode_label == strings.mode_single:
        _render_single_shot(strings, controller)
    else:
        _render_pwm(strings, controller)

    st.divider()
    _render_status(strings, controller)


def _render_single_shot(strings: Strings, controller: TriggerController) -> None:
    st.subheader(strings.single_header)
    with st.form(key="single_shot_form", clear_on_submit=False):
        pulse_ms = st.slider(
            strings.single_pulse_label,
            min_value=float(PULSE_MIN_MS),
            max_value=float(PULSE_MAX_MS),
            value=float(st.session_state.get("pulse_ms", 10.0)),
            step=0.1,
            help=strings.single_pulse_help,
        )
        apply_clicked = st.form_submit_button(strings.single_apply)
    if apply_clicked:
        st.session_state["pulse_ms"] = pulse_ms

    fire_clicked = st.button(strings.single_fire, type="primary", use_container_width=True)
    if fire_clicked:
        params = SingleShotParams(pulse_ms=st.session_state.get("pulse_ms", pulse_ms))
        try:
            controller.fire_single_shot(params)
            st.success(strings.ok_pulse_fired.format(ms=params.pulse_ms))
        except TriggerControllerError as exc:
            st.error(str(exc))


def _render_pwm(strings: Strings, controller: TriggerController) -> None:
    st.subheader(strings.pwm_header)
    with st.form(key="pwm_form", clear_on_submit=False):
        freq = st.slider(
            strings.pwm_freq_label,
            min_value=float(FREQ_MIN_HZ),
            max_value=float(FREQ_MAX_HZ),
            value=float(st.session_state.get("pwm_freq", 100.0)),
            step=1.0,
            help=strings.pwm_freq_help,
        )
        duty = st.slider(
            strings.pwm_duty_label,
            min_value=float(DUTY_MIN_PCT),
            max_value=float(DUTY_MAX_PCT),
            value=float(st.session_state.get("pwm_duty", 50.0)),
            step=1.0,
            help=strings.pwm_duty_help,
        )
        apply_clicked = st.form_submit_button(strings.single_apply)
    if apply_clicked:
        st.session_state["pwm_freq"] = freq
        st.session_state["pwm_duty"] = duty

    col_start, col_stop = st.columns(2)
    start_clicked = col_start.button(strings.pwm_start, type="primary", use_container_width=True)
    stop_clicked = col_stop.button(strings.pwm_stop, use_container_width=True)

    if start_clicked:
        params = PwmParams(
            frequency_hz=st.session_state.get("pwm_freq", freq),
            duty_cycle_pct=st.session_state.get("pwm_duty", duty),
        )
        try:
            was_running = controller.mode == TriggerMode.PWM
            controller.start_pwm(params)
            template = strings.ok_pwm_updated if was_running else strings.ok_pwm_started
            st.success(
                template.format(hz=params.frequency_hz, duty=params.duty_cycle_pct)
            )
        except TriggerControllerError as exc:
            st.error(str(exc))

    if stop_clicked:
        try:
            controller.stop()
            st.success(strings.ok_stopped)
        except TriggerControllerError as exc:
            st.error(str(exc))


def _render_status(strings: Strings, controller: TriggerController) -> None:
    st.subheader(strings.status_header)
    mode = controller.mode
    st.write(f"**{strings.status_mode}:** `{mode.value}`")
    if controller.pulse_in_flight:
        st.info(strings.status_pulse_running)
    pwm = controller.current_pwm
    if pwm is not None:
        st.write(
            f"**{strings.status_current_pwm}:** "
            f"{pwm.frequency_hz:.1f} Hz, duty {pwm.duty_cycle_pct:.1f} %"
        )
    err = controller.last_error
    if err:
        st.warning(f"**{strings.status_last_error}:** {err}")
    if os.environ.get("VC_TRIGGER_MOCK", "0") == "1":
        st.caption(strings.warn_hw_not_available)


def main() -> None:
    configure_logging()
    st.set_page_config(
        page_title="notavis-mipi-trigger",
        page_icon="⚡",
        layout="centered",
    )
    lang_label = st.sidebar.selectbox("Sprache / Language", list(_LANG_MAP.keys()), index=0)
    strings = _LANG_MAP[lang_label]
    _render(strings)


# ``streamlit run src/vc_trigger/ui.py`` executes the module as a script, so
# ``__name__ == "__main__"`` holds and ``main()`` runs on every rerun. The
# console script ``vc-trigger-ui`` (see pyproject.toml) also calls ``main``
# directly. Importing this module (e.g. from a test) does NOT trigger the UI.
if __name__ == "__main__":
    main()
