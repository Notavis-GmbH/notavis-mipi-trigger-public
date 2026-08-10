"""Shared pytest fixtures for the trigger controller test suite."""

from __future__ import annotations

import os

# Force Qt into a headless backend BEFORE any PySide6 import happens. Individual
# test modules that import PySide6 rely on this being set at collection time.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from vc_trigger.controller import TriggerController, reset_controller_for_tests


@pytest.fixture
def mock_controller() -> TriggerController:
    """A fresh mock-mode TriggerController for each test."""
    reset_controller_for_tests()
    ctrl = TriggerController(pin=18, mock=True)
    yield ctrl
    ctrl.shutdown()
    reset_controller_for_tests()
