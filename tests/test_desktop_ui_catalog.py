"""UI tests for the catalog-only detection state (PR #11).

These exercise the third visual mode of the sensor-test tab:

* Detected sensor has **no** live profile but **does** have a catalog
  entry. The teal ``✓`` label must stay hidden, the magenta error banner
  must stay hidden, and the new warm-orange ``◐`` catalog banner must
  show the sensor's display name.

The tests do not touch v4l2-ctl — they inject state directly via the
mock ``SensorController`` and set ``_sensor_catalog`` before calling
``_apply_sensor_profile`` again. This keeps them independent from the
board and from the ``VC_TRIGGER_MOCK`` env var.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6", reason="PySide6 optional-extra [desktop] not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vc_trigger.desktop_ui import TriggerMainWindow  # noqa: E402
from vc_trigger.controller import TriggerController  # noqa: E402
from vc_trigger.models import SensorPixelFormat  # noqa: E402
from vc_trigger.sensor_catalog_loader import load_catalog_entry  # noqa: E402
from vc_trigger.sensor_controller import SensorController  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-scoped ``QApplication`` — mirrors ``test_desktop_ui.py``."""
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture
def catalog_window(
    qapp: QApplication,
    mock_controller: TriggerController,
) -> TriggerMainWindow:
    """Window with mock sensor controller and IMX296 catalog state injected."""
    sensor_controller = SensorController(mock=True)
    w = TriggerMainWindow(
        controller=mock_controller, sensor_controller=sensor_controller,
    )
    # Simulate a discover_sensor() result with catalog-only status.
    w._sensor_profile = None
    w._sensor_catalog = load_catalog_entry("IMX296")
    w._sensor_detect_error = None
    w._apply_sensor_profile()
    w._populate_pixel_format_combo()
    yield w
    w.close()


def test_catalog_banner_visible_for_catalog_only_sensor(
    catalog_window: TriggerMainWindow,
) -> None:
    """Catalog banner shows, live-check label + error banner stay hidden.

    Uses ``isHidden()`` rather than ``isVisible()`` because the test
    fixture never calls ``show()`` on the top-level window — Qt only
    reports ``isVisible() == True`` when the whole parent chain is
    visible, which requires an event-loop cycle after ``show()``.
    ``isHidden()`` directly reflects the widget-local state we set via
    ``setVisible()`` in ``_apply_sensor_profile()``.
    """
    assert not catalog_window._sensor_catalog_label.isHidden()
    assert catalog_window._sensor_detected_label.isHidden()
    assert catalog_window._sensor_error_label.isHidden()


def test_catalog_banner_names_the_detected_sensor(
    catalog_window: TriggerMainWindow,
) -> None:
    """The banner text must include the display name and native resolution."""
    text = catalog_window._sensor_catalog_label.text()
    assert "IMX296" in text
    # IMX296 native active area: 1440x1080 per driver source.
    assert "1440" in text
    assert "1080" in text
    # Must communicate the "not yet verified" caveat to the user.
    assert "nicht verifiziert" in text or "not verified" in text


def test_pixel_format_combo_uses_catalog_format_options(
    catalog_window: TriggerMainWindow,
) -> None:
    """With a catalog entry the combo must be populated from catalog modes."""
    combo = catalog_window._sensor_format_combo
    assert combo.count() > 0
    # IMX296 declares RAW08 and RAW10 in its mode matrix.
    values = {combo.itemData(i) for i in range(combo.count())}
    assert SensorPixelFormat.RAW10.value in values
    # Default should prefer RAW10 when available.
    assert combo.currentData() == SensorPixelFormat.RAW10.value


def test_live_state_still_uses_teal_check_label(
    qapp: QApplication,
    mock_controller: TriggerController,
) -> None:
    """Regression: a live-verified profile must still hide the catalog banner."""
    from vc_trigger.sensor_profiles_loader import load_profile

    sensor_controller = SensorController(mock=True)
    w = TriggerMainWindow(
        controller=mock_controller, sensor_controller=sensor_controller,
    )
    try:
        w._sensor_profile = load_profile("OV9281")
        w._sensor_catalog = None
        w._sensor_detect_error = None
        w._apply_sensor_profile()

        assert not w._sensor_detected_label.isHidden()
        assert w._sensor_catalog_label.isHidden()
        assert w._sensor_error_label.isHidden()
        assert "OV9281" in w._sensor_detected_label.text()
    finally:
        w.close()
