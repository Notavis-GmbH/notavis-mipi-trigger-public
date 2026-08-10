"""Structured logging setup for the trigger app.

Kept dependency-free so it also works in tests without the Streamlit stack.
"""

from __future__ import annotations

import logging
import os
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str | int | None = None) -> None:
    """Configure the root logger once per process.

    The log level is taken from the ``VC_TRIGGER_LOG_LEVEL`` environment
    variable if not passed explicitly. Default is ``INFO``.
    """
    effective = level or os.environ.get("VC_TRIGGER_LOG_LEVEL", "INFO")
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. by Streamlit) — just adjust the level.
        root.setLevel(effective)
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(effective)
