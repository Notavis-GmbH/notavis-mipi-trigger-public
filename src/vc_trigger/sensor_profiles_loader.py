"""Loader for the sensor profile registry.

The registry lives as YAML files under :mod:`vc_trigger.sensor_profiles`;
one file per VC MIPI sensor, named ``<sensor_name>.yaml`` where
``sensor_name`` is the exact string returned by the VC driver's
``sensor_name`` V4L2 control on the sensor subdev.

Detection flow (as used by the desktop UI):

1. Read ``sensor_name`` from the sensor subdev via ``v4l2-ctl``.
2. Look up ``<sensor_name>.yaml`` in this package's resource dir.
3. If found, parse into a :class:`SensorProfile` and use it to
   drive UI ranges, format choices and control names.
4. If not found, raise :class:`UnknownSensorError` so the UI can
   surface a "sensor XY not in registry — add profile under
   ``sensor_profiles/``" message.

The loader has no PySide6 or V4L2 dependency; it is pure Python + PyYAML.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml

from .models import SensorPixelFormat

_LOG = logging.getLogger(__name__)

_PROFILE_PACKAGE = "vc_trigger.sensor_profiles"


class SensorProfileError(RuntimeError):
    """Raised when a profile YAML is malformed."""


class UnknownSensorError(LookupError):
    """Raised when no profile matches the reported ``sensor_name``."""


@dataclass(frozen=True)
class PixelFormatEntry:
    """One pixel format supported by a sensor profile."""

    id: SensorPixelFormat
    fourcc: str
    label: str


@dataclass(frozen=True)
class ControlBounds:
    """Bounds and metadata for one V4L2 control."""

    v4l2_name: str
    min: int
    max: int
    default: int
    step: int = 1
    unit: str = ""


@dataclass(frozen=True)
class SensorProfile:
    """Parsed sensor profile."""

    sensor_name: str
    display_name: str
    vendor: str
    native_width: int
    native_height: int
    mediabus_code: str
    pixel_formats: tuple[PixelFormatEntry, ...]
    default_pixel_format: SensorPixelFormat
    controls: dict[str, ControlBounds] = field(default_factory=dict)

    def fourcc_for(self, fmt: SensorPixelFormat) -> str:
        """Return the V4L2 fourcc for ``fmt`` as declared in this profile."""
        for entry in self.pixel_formats:
            if entry.id == fmt:
                return entry.fourcc
        raise KeyError(f"pixel format {fmt} not in profile {self.sensor_name}")


def load_profile(sensor_name: str) -> SensorProfile:
    """Load the profile matching ``sensor_name`` from the registry.

    Raises :class:`UnknownSensorError` if no matching YAML exists.
    """
    filename = f"{sensor_name}.yaml"
    try:
        with resources.files(_PROFILE_PACKAGE).joinpath(filename).open("rb") as fh:
            payload = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise UnknownSensorError(
            f"no sensor profile for {sensor_name!r}; add {filename} to "
            f"src/vc_trigger/sensor_profiles/"
        ) from exc
    return _parse_profile(payload, source=filename)


def available_profiles() -> list[str]:
    """Return the list of ``sensor_name`` values with a registered profile."""
    root = resources.files(_PROFILE_PACKAGE)
    return sorted(
        p.name.removesuffix(".yaml")
        for p in root.iterdir()
        if p.name.endswith(".yaml")
    )


def load_profile_from_path(path: Path) -> SensorProfile:
    """Load a profile from an arbitrary filesystem path.

    Only used by tests and by dev tooling. Production callers should use
    :func:`load_profile` so profiles ship with the package.
    """
    with path.open("rb") as fh:
        payload = yaml.safe_load(fh)
    return _parse_profile(payload, source=str(path))


def _parse_profile(payload: object, *, source: str) -> SensorProfile:
    if not isinstance(payload, dict):
        raise SensorProfileError(f"{source}: top-level must be a mapping")
    try:
        native = payload["native"]
        pf_entries = payload["pixel_formats"]
        default_pf = payload["default_pixel_format"]
        controls_yaml = payload.get("controls", {}) or {}
    except KeyError as exc:
        raise SensorProfileError(f"{source}: missing key {exc.args[0]!r}") from exc

    pixel_formats: list[PixelFormatEntry] = []
    for raw in pf_entries:
        try:
            pixel_formats.append(
                PixelFormatEntry(
                    id=SensorPixelFormat(raw["id"]),
                    fourcc=str(raw["fourcc"]),
                    label=str(raw.get("label", raw["id"])),
                )
            )
        except (KeyError, ValueError) as exc:
            raise SensorProfileError(
                f"{source}: bad pixel_format entry {raw!r}: {exc}"
            ) from exc

    try:
        default_pf_enum = SensorPixelFormat(default_pf)
    except ValueError as exc:
        raise SensorProfileError(
            f"{source}: default_pixel_format {default_pf!r} is not a valid SensorPixelFormat"
        ) from exc
    if not any(pf.id == default_pf_enum for pf in pixel_formats):
        raise SensorProfileError(
            f"{source}: default_pixel_format {default_pf!r} is not in pixel_formats"
        )

    controls: dict[str, ControlBounds] = {}
    for name, raw in controls_yaml.items():
        try:
            controls[name] = ControlBounds(
                v4l2_name=str(raw.get("v4l2_name", name)),
                min=int(raw["min"]),
                max=int(raw["max"]),
                default=int(raw["default"]),
                step=int(raw.get("step", 1)),
                unit=str(raw.get("unit", "")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise SensorProfileError(
                f"{source}: bad control entry {name!r}: {exc}"
            ) from exc

    try:
        return SensorProfile(
            sensor_name=str(payload["sensor_name"]),
            display_name=str(payload.get("display_name", payload["sensor_name"])),
            vendor=str(payload.get("vendor", "unknown")),
            native_width=int(native["width"]),
            native_height=int(native["height"]),
            mediabus_code=str(native.get("mediabus_code", "")),
            pixel_formats=tuple(pixel_formats),
            default_pixel_format=default_pf_enum,
            controls=controls,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SensorProfileError(f"{source}: malformed native block: {exc}") from exc


__all__ = [
    "ControlBounds",
    "PixelFormatEntry",
    "SensorProfile",
    "SensorProfileError",
    "UnknownSensorError",
    "available_profiles",
    "load_profile",
    "load_profile_from_path",
]
