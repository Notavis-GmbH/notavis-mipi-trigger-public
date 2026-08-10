"""notavis-mipi-trigger — external GPIO/PWM trigger for VC MIPI cameras.

This package provides:

- :mod:`vc_trigger.controller`  — thread-safe GPIO/PWM controller for GPIO 18
- :mod:`vc_trigger.models`      — Pydantic parameter models with hard limits
- :mod:`vc_trigger.ui`          — Streamlit UI (DE/EN toggle)
- :mod:`vc_trigger.logging_setup` — structured logging setup

The controller is designed to run as an unprivileged user (`notavis`) on a
Raspberry Pi CM5 running Debian 13 (Trixie) with the `lgpio` pin factory.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
