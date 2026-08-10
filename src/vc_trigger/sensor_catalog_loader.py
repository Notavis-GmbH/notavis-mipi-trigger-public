"""Loader for the VC MIPI sensor catalog registry.

The catalog registry lives as YAML files under
:mod:`vc_trigger.sensor_profiles.catalog`; one file per VC MIPI sensor
recognized by the ``vc_mipi_core`` driver on the Raspberry Pi CM5 branch.

Each catalog entry contains only the metadata that can be derived from
the driver's canonical source
(``VC-MIPI-modules/vc_mipi_core@raspberrypi/develop/src/vc_mipi_modules.c``):

* Module ID (``MOD_ID_*`` define in ``vc_mipi_modules.h``)
* Native active resolution (from ``FRAME(...)`` macros)
* Shutter type and color/mono capability (from the driver README)
* Mode matrix (lane options, format options, binning support)

It does **not** contain runtime-dependent values such as V4L2 mediabus
codes, fourcc mappings or exposure/gain bounds — those live in the
"live" profiles under :mod:`vc_trigger.sensor_profiles` and are only
added once a sensor has been physically verified on a Notavis board.

Detection flow (as used by the desktop UI, extended in PR #10):

1. Read ``sensor_name`` from the sensor subdev via ``v4l2-ctl``.
2. First look up a live profile via
   :func:`vc_trigger.sensor_profiles_loader.load_profile`.
3. If none exists, fall back to :func:`load_catalog_entry` to at least
   populate the UI dropdown, module-ID auto-detection and the
   "sensor recognized but not yet verified" banner.

The loader has no PySide6 or V4L2 dependency; it is pure Python + PyYAML.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml

_LOG = logging.getLogger(__name__)

_CATALOG_PACKAGE = "vc_trigger.sensor_profiles.catalog"

VerificationStatus = Literal["catalog_only", "live_verified"]


class SensorCatalogError(RuntimeError):
    """Raised when a catalog YAML is malformed."""


class UnknownCatalogSensorError(LookupError):
    """Raised when no catalog entry matches the requested key."""


@dataclass(frozen=True)
class VerificationInfo:
    """Provenance of a catalog entry."""

    status: VerificationStatus
    source: str
    verified_at: date


@dataclass(frozen=True)
class NativeFrame:
    """Native active pixel area of the sensor."""

    width: int
    height: int


@dataclass(frozen=True)
class ModeMatrix:
    """Aggregated properties across all modes exposed by the driver."""

    mode_count: int
    lane_options: tuple[int, ...]
    format_options: tuple[str, ...]
    has_binning: bool


@dataclass(frozen=True)
class CatalogEntry:
    """One VC MIPI sensor known to the ``vc_mipi_core`` driver."""

    sensor_name: str
    display_name: str
    vendor: str
    module_id: int
    native: NativeFrame
    shutter: Literal["global", "rolling"]
    color_mono: Literal["mono", "color+mono"]
    modes: ModeMatrix
    verification: VerificationInfo
    notes: str = ""


def load_catalog_entry(sensor_name: str) -> CatalogEntry:
    """Load the catalog entry matching ``sensor_name`` from the registry.

    Raises :class:`UnknownCatalogSensorError` if no matching YAML exists.
    """
    filename = f"{sensor_name}.yaml"
    try:
        with resources.files(_CATALOG_PACKAGE).joinpath(filename).open("rb") as fh:
            payload = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise UnknownCatalogSensorError(
            f"no catalog entry for {sensor_name!r}; add {filename} to "
            f"src/vc_trigger/sensor_profiles/catalog/"
        ) from exc
    return _parse_entry(payload, source=filename)


def load_catalog_entry_from_path(path: Path) -> CatalogEntry:
    """Load a catalog entry from an arbitrary filesystem path (dev/tests)."""
    with path.open("rb") as fh:
        payload = yaml.safe_load(fh)
    return _parse_entry(payload, source=str(path))


def available_catalog_entries() -> list[str]:
    """Return the ``sensor_name`` values with a registered catalog YAML."""
    root = resources.files(_CATALOG_PACKAGE)
    return sorted(
        p.name.removesuffix(".yaml")
        for p in root.iterdir()
        if p.name.endswith(".yaml")
    )


def resolve_by_module_id(module_id: int) -> CatalogEntry:
    """Return the catalog entry whose ``module_id`` matches ``module_id``.

    Raises :class:`UnknownCatalogSensorError` if none matches.
    """
    for name in available_catalog_entries():
        entry = load_catalog_entry(name)
        if entry.module_id == module_id:
            return entry
    raise UnknownCatalogSensorError(
        f"no catalog entry with module_id=0x{module_id:04x}"
    )


def _parse_entry(payload: object, *, source: str) -> CatalogEntry:
    if not isinstance(payload, dict):
        raise SensorCatalogError(f"{source}: top-level must be a mapping")
    try:
        sensor_name = str(payload["sensor_name"])
        module_id_raw = payload["module_id"]
        native_yaml = payload["native"]
        shutter = payload["shutter"]
        color_mono = payload["color_mono"]
        modes_yaml = payload["modes"]
        verification_yaml = payload["verification"]
    except KeyError as exc:
        raise SensorCatalogError(f"{source}: missing key {exc.args[0]!r}") from exc

    module_id = _parse_module_id(module_id_raw, source=source)
    native = _parse_native(native_yaml, source=source)
    modes = _parse_modes(modes_yaml, source=source)
    verification = _parse_verification(verification_yaml, source=source)

    if shutter not in ("global", "rolling"):
        raise SensorCatalogError(
            f"{source}: shutter must be 'global' or 'rolling', got {shutter!r}"
        )
    if color_mono not in ("mono", "color+mono"):
        raise SensorCatalogError(
            f"{source}: color_mono must be 'mono' or 'color+mono', got {color_mono!r}"
        )

    return CatalogEntry(
        sensor_name=sensor_name,
        display_name=str(payload.get("display_name", sensor_name)),
        vendor=str(payload.get("vendor", "unknown")),
        module_id=module_id,
        native=native,
        shutter=shutter,
        color_mono=color_mono,
        modes=modes,
        verification=verification,
        notes=str(payload.get("notes", "")),
    )


def _parse_module_id(raw: object, *, source: str) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw, 0)
        except ValueError as exc:
            raise SensorCatalogError(
                f"{source}: module_id {raw!r} is not a parseable integer"
            ) from exc
    raise SensorCatalogError(
        f"{source}: module_id must be int or hex string, got {type(raw).__name__}"
    )


def _parse_native(raw: object, *, source: str) -> NativeFrame:
    if not isinstance(raw, dict):
        raise SensorCatalogError(f"{source}: native must be a mapping")
    try:
        return NativeFrame(width=int(raw["width"]), height=int(raw["height"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise SensorCatalogError(f"{source}: malformed native block: {exc}") from exc


def _parse_modes(raw: object, *, source: str) -> ModeMatrix:
    if not isinstance(raw, dict):
        raise SensorCatalogError(f"{source}: modes must be a mapping")
    try:
        return ModeMatrix(
            mode_count=int(raw["mode_count"]),
            lane_options=tuple(int(x) for x in raw["lane_options"]),
            format_options=tuple(str(x) for x in raw["format_options"]),
            has_binning=bool(raw["has_binning"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SensorCatalogError(f"{source}: malformed modes block: {exc}") from exc


def _parse_verification(raw: object, *, source: str) -> VerificationInfo:
    if not isinstance(raw, dict):
        raise SensorCatalogError(f"{source}: verification must be a mapping")
    try:
        status = raw["status"]
        if status not in ("catalog_only", "live_verified"):
            raise SensorCatalogError(
                f"{source}: verification.status must be 'catalog_only' or "
                f"'live_verified', got {status!r}"
            )
        verified_at_raw = raw["verified_at"]
        if isinstance(verified_at_raw, date):
            verified_at = verified_at_raw
        else:
            verified_at = date.fromisoformat(str(verified_at_raw))
        return VerificationInfo(
            status=status,
            source=str(raw["source"]),
            verified_at=verified_at,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SensorCatalogError(
            f"{source}: malformed verification block: {exc}"
        ) from exc


__all__ = [
    "CatalogEntry",
    "ModeMatrix",
    "NativeFrame",
    "SensorCatalogError",
    "UnknownCatalogSensorError",
    "VerificationInfo",
    "VerificationStatus",
    "available_catalog_entries",
    "load_catalog_entry",
    "load_catalog_entry_from_path",
    "resolve_by_module_id",
]
