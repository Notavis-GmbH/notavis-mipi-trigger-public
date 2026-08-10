"""Tests for the VC MIPI sensor catalog loader."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from vc_trigger.sensor_catalog_loader import (
    CatalogEntry,
    SensorCatalogError,
    UnknownCatalogSensorError,
    available_catalog_entries,
    load_catalog_entry,
    load_catalog_entry_from_path,
    resolve_by_module_id,
)


# The 25 VC MIPI sensors recognized by vc_mipi_core on the
# raspberrypi/develop branch as of 2026-08-04. Kept as a canonical
# fixture so drift between the driver source and this repo shows up
# in CI immediately.
EXPECTED_SENSORS: tuple[tuple[str, int], ...] = (
    ("IMX178", 0x0178), ("IMX183", 0x0183), ("IMX226", 0x0226),
    ("IMX250", 0x0250), ("IMX252", 0x0252),
    ("IMX264", 0x0264), ("IMX265", 0x0265),
    ("IMX273", 0x0273),
    ("IMX290", 0x0290), ("IMX296", 0x0296), ("IMX297", 0x0297),
    ("IMX327", 0x0327), ("IMX335", 0x0335), ("IMX392", 0x0392),
    ("IMX412", 0x0412), ("IMX415", 0x0415), ("IMX462", 0x0462),
    ("IMX565", 0x0565), ("IMX566", 0x0566), ("IMX567", 0x0567),
    ("IMX568", 0x0568),
    ("IMX585", 0x0585), ("IMX900", 0x0900),
    ("OV7251", 0x7251), ("OV9281", 0x9281),
)


def test_all_25_sensors_registered() -> None:
    """All 25 canonical sensors must have a catalog YAML."""
    registered = set(available_catalog_entries())
    expected = {name for name, _ in EXPECTED_SENSORS}
    assert registered == expected, (
        f"missing: {expected - registered}, extra: {registered - expected}"
    )


@pytest.mark.parametrize("sensor_name,module_id", EXPECTED_SENSORS)
def test_catalog_entry_roundtrip(sensor_name: str, module_id: int) -> None:
    """Every catalog YAML parses into a valid CatalogEntry."""
    entry = load_catalog_entry(sensor_name)
    assert isinstance(entry, CatalogEntry)
    assert entry.sensor_name == sensor_name
    assert entry.module_id == module_id
    assert entry.native.width > 0
    assert entry.native.height > 0
    assert entry.shutter in ("global", "rolling")
    assert entry.color_mono in ("mono", "color+mono")
    assert entry.modes.mode_count > 0
    assert entry.verification.status in ("catalog_only", "live_verified")
    assert entry.verification.source.startswith("https://github.com/")
    assert isinstance(entry.verification.verified_at, date)


def test_module_ids_are_unique() -> None:
    """No two catalog entries may share a module_id."""
    seen: dict[int, str] = {}
    for name in available_catalog_entries():
        entry = load_catalog_entry(name)
        if entry.module_id in seen:
            pytest.fail(
                f"module_id collision: {entry.sensor_name} and "
                f"{seen[entry.module_id]} both use 0x{entry.module_id:04x}"
            )
        seen[entry.module_id] = entry.sensor_name


@pytest.mark.parametrize("sensor_name,module_id", EXPECTED_SENSORS)
def test_resolve_by_module_id(sensor_name: str, module_id: int) -> None:
    entry = resolve_by_module_id(module_id)
    assert entry.sensor_name == sensor_name


def test_resolve_unknown_module_id_raises() -> None:
    with pytest.raises(UnknownCatalogSensorError):
        resolve_by_module_id(0xDEAD)


def test_unknown_sensor_raises() -> None:
    with pytest.raises(UnknownCatalogSensorError):
        load_catalog_entry("IMX999_DOES_NOT_EXIST")


def test_malformed_missing_module_id(tmp_path: Path) -> None:
    payload = tmp_path / "BadSensor.yaml"
    payload.write_text(
        "sensor_name: BadSensor\n"
        "native: {width: 100, height: 100}\n"
        "shutter: global\n"
        "color_mono: mono\n"
        "modes: {mode_count: 1, lane_options: [2], "
        "format_options: [RAW10], has_binning: false}\n"
        "verification:\n"
        "  status: catalog_only\n"
        "  source: 'https://example.com'\n"
        "  verified_at: '2026-08-04'\n",
        encoding="utf-8",
    )
    with pytest.raises(SensorCatalogError):
        load_catalog_entry_from_path(payload)


def test_malformed_invalid_shutter(tmp_path: Path) -> None:
    payload = tmp_path / "BadSensor.yaml"
    payload.write_text(
        "sensor_name: BadSensor\n"
        "module_id: '0x0001'\n"
        "native: {width: 100, height: 100}\n"
        "shutter: hybrid\n"
        "color_mono: mono\n"
        "modes: {mode_count: 1, lane_options: [2], "
        "format_options: [RAW10], has_binning: false}\n"
        "verification:\n"
        "  status: catalog_only\n"
        "  source: 'https://example.com'\n"
        "  verified_at: '2026-08-04'\n",
        encoding="utf-8",
    )
    with pytest.raises(SensorCatalogError, match="shutter"):
        load_catalog_entry_from_path(payload)


def test_malformed_invalid_verification_status(tmp_path: Path) -> None:
    payload = tmp_path / "BadSensor.yaml"
    payload.write_text(
        "sensor_name: BadSensor\n"
        "module_id: '0x0001'\n"
        "native: {width: 100, height: 100}\n"
        "shutter: global\n"
        "color_mono: mono\n"
        "modes: {mode_count: 1, lane_options: [2], "
        "format_options: [RAW10], has_binning: false}\n"
        "verification:\n"
        "  status: fake_status\n"
        "  source: 'https://example.com'\n"
        "  verified_at: '2026-08-04'\n",
        encoding="utf-8",
    )
    with pytest.raises(SensorCatalogError, match="verification.status"):
        load_catalog_entry_from_path(payload)


def test_imx296_has_binning_flag() -> None:
    """IMX296 driver source declares binning modes (vc_mipi_modules.c L420)."""
    entry = load_catalog_entry("IMX296")
    assert entry.modes.has_binning is True


def test_imx568_is_global_shutter() -> None:
    """IMX568 is a global-shutter CMOS per VC-Core README."""
    entry = load_catalog_entry("IMX568")
    assert entry.shutter == "global"


def test_ov9281_is_mono_only() -> None:
    """OV9281 is monochrome-only per VC-Core README."""
    entry = load_catalog_entry("OV9281")
    assert entry.color_mono == "mono"
