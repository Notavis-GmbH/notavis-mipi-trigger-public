"""Sensor controller for the VC MIPI sensor tester tab.

Wraps ``v4l2-ctl`` calls against the sensor subdev (``/dev/v4l-subdev2`` on
CM5 with VC driver v0.6.10 and OV9281). Kept intentionally separate from
:mod:`vc_trigger.controller`, which owns the GPIO/PWM trigger source.

Design notes:

- The controller shells out to ``v4l2-ctl`` — no ``python-v4l2`` binding is
  imported, so the sensor tab has zero extra runtime dependencies.
- All subprocess calls have a timeout and a non-empty argv; the shell is
  never invoked (``shell=False``).
- The mock backend is deterministic and returns a fixed control set matching
  the VC driver v0.6.10 layout, so tests can run off-board.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .models import SensorParams, SensorPixelFormat, SensorVendor
from .sensor_catalog_loader import (
    CatalogEntry,
    UnknownCatalogSensorError,
    load_catalog_entry,
)
from .sensor_profiles_loader import SensorProfile, UnknownSensorError, load_profile

_LOG = logging.getLogger(__name__)

DEFAULT_SENSOR_SUBDEV = "/dev/v4l-subdev2"
DEFAULT_VIDEO_DEVICE = "/dev/video0"
DEFAULT_TIMEOUT_S = 5.0

# Mediabus codes used by the VC driver on Raspberry Pi CM5.
_PIXEL_FORMAT_MEDIABUS_CODE = {
    SensorPixelFormat.RAW08: "0x2001",  # MEDIA_BUS_FMT_Y8_1X8
    SensorPixelFormat.RAW10: "0x200a",  # MEDIA_BUS_FMT_Y10_1X10
}
# Legacy fourcc map used only when no sensor profile is supplied. Kept for
# backwards compatibility with existing tests and callers that do not yet
# pass a :class:`SensorProfile`; production code should always inject a
# profile so the mapping comes from the registry.
_LEGACY_PIXEL_FORMAT_FOURCC = {
    SensorPixelFormat.RAW08: "GREY",
    SensorPixelFormat.RAW10: "Y10P",
}


class SensorControllerError(RuntimeError):
    """Raised when a v4l2-ctl invocation fails or returns garbled output."""


@dataclass(frozen=True)
class SensorSnapshot:
    """Read-back of the sensor state from V4L2 controls."""

    sensor_name: str
    exposure_us: int
    gain: int
    trigger_mode: int
    pixel_format: SensorPixelFormat | None
    raw_controls: dict[str, str] = field(default_factory=dict)


class SensorController:
    """Thin subprocess wrapper around ``v4l2-ctl``.

    All methods either succeed silently or raise :class:`SensorControllerError`
    with the verbatim stderr appended, so the UI can show the driver-side
    reason for a rejected write.
    """

    def __init__(
        self,
        *,
        subdev: str = DEFAULT_SENSOR_SUBDEV,
        video_device: str = DEFAULT_VIDEO_DEVICE,
        mock: bool = False,
        v4l2_ctl_binary: str = "v4l2-ctl",
        run_as_user: str | None = "notavis",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        profile: SensorProfile | None = None,
    ) -> None:
        self._subdev = subdev
        self._video_device = video_device
        self._mock = mock
        self._binary = v4l2_ctl_binary
        self._run_as_user = run_as_user
        self._timeout_s = timeout_s
        self._profile = profile
        self._mock_state: dict[str, int] = {
            "exposure": 10_000,
            "gain": 0,
            "trigger_mode": 0,
        }
        self._mock_pixel_format = SensorPixelFormat.RAW10

    # ---------- public API -------------------------------------------------

    @property
    def is_mock(self) -> bool:
        return self._mock

    def read(self) -> SensorSnapshot:
        """Return the current sensor state as a :class:`SensorSnapshot`."""
        if self._mock:
            return SensorSnapshot(
                sensor_name="MOCK_OV9281",
                exposure_us=self._mock_state["exposure"],
                gain=self._mock_state["gain"],
                trigger_mode=self._mock_state["trigger_mode"],
                pixel_format=self._mock_pixel_format,
                raw_controls={k: str(v) for k, v in self._mock_state.items()},
            )
        out = self._run_v4l2_ctl(["-d", self._subdev, "-C",
                                  "exposure,analogue_gain,trigger_mode,sensor_name"])
        controls = _parse_control_dump(out)
        try:
            snapshot = SensorSnapshot(
                sensor_name=controls.get("sensor_name", "unknown"),
                exposure_us=int(controls["exposure"]),
                gain=int(controls["analogue_gain"]),
                trigger_mode=int(controls["trigger_mode"]),
                pixel_format=self._read_pixel_format(),
                raw_controls=controls,
            )
        except (KeyError, ValueError) as exc:  # pragma: no cover - defensive
            raise SensorControllerError(
                f"could not parse v4l2 control output: {out!r}"
            ) from exc
        return snapshot

    def apply(self, params: SensorParams) -> None:
        """Write ``params`` to the sensor.

        Writes are ordered so that a failure leaves the sensor in a
        predictable half-applied state that the next :meth:`read` will
        surface: exposure and gain first (fast, hardware-only), then
        trigger mode, then pixel format (may require re-configuring the
        video device).
        """
        if self._mock:
            self._mock_state["exposure"] = params.exposure_us
            self._mock_state["gain"] = params.gain
            self._mock_state["trigger_mode"] = params.trigger_mode
            self._mock_pixel_format = params.pixel_format
            return
        controls = (
            f"exposure={params.exposure_us},"
            f"analogue_gain={params.gain},"
            f"trigger_mode={params.trigger_mode}"
        )
        self._run_v4l2_ctl(["-d", self._subdev, "-c", controls])
        self._write_pixel_format(params.pixel_format)

    def fire_single_trigger(self) -> None:
        """Fire an internal single trigger via the ``single_trigger`` control."""
        if self._mock:
            _LOG.debug("mock single_trigger fired")
            return
        self._run_v4l2_ctl(["-d", self._subdev, "-c", "single_trigger=1"])

    @property
    def profile(self) -> SensorProfile | None:
        """The sensor profile driving fourcc mapping, or ``None`` for legacy mode."""
        return self._profile

    def capture_frames(
        self,
        *,
        count: int,
        output_dir: Path,
        pixel_format: SensorPixelFormat,
    ) -> Path:
        """Capture ``count`` frames via ``v4l2-ctl --stream-mmap``.

        Returns the path of the resulting binary file. The caller is
        responsible for managing the output directory lifecycle.
        """
        if count <= 0:
            raise ValueError("count must be positive")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"capture-{count}f.raw"
        if self._mock:
            target.write_bytes(b"\x00" * 32)
            return target
        fourcc = self._fourcc_for(pixel_format)
        self._run_v4l2_ctl([
            "-d", self._video_device,
            "--set-fmt-video", f"pixelformat={fourcc}",
        ])
        self._run_v4l2_ctl([
            "-d", self._video_device,
            "--stream-mmap",
            f"--stream-count={count}",
            f"--stream-to={target}",
        ])
        return target

    # ---------- internals --------------------------------------------------

    def _read_pixel_format(self) -> SensorPixelFormat | None:
        out = self._run_v4l2_ctl([
            "-d", self._video_device, "--get-fmt-video",
        ])
        fourcc = _extract_fourcc(out)
        for fmt in SensorPixelFormat:
            if self._fourcc_for(fmt) == fourcc:
                return fmt
        return None

    def _write_pixel_format(self, pixel_format: SensorPixelFormat) -> None:
        fourcc = self._fourcc_for(pixel_format)
        self._run_v4l2_ctl([
            "-d", self._video_device,
            "--set-fmt-video", f"pixelformat={fourcc}",
        ])

    def _fourcc_for(self, pixel_format: SensorPixelFormat) -> str:
        """Map ``pixel_format`` to a fourcc via the profile if given, else legacy."""
        if self._profile is not None:
            try:
                return self._profile.fourcc_for(pixel_format)
            except KeyError:
                # Profile lacks this format — fall through to legacy so the
                # UI can still request RAW08/RAW10 during migration.
                pass
        return _LEGACY_PIXEL_FORMAT_FOURCC[pixel_format]

    def _run_v4l2_ctl(self, args: Sequence[str]) -> str:
        argv: list[str] = []
        if self._run_as_user and self._run_as_user != _current_user():
            argv.extend(["sudo", "-n", "-u", self._run_as_user])
        argv.append(self._binary)
        argv.extend(args)
        _LOG.info("v4l2-ctl %s", " ".join(shlex.quote(a) for a in argv))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SensorControllerError(f"v4l2-ctl binary not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SensorControllerError(
                f"v4l2-ctl timed out after {self._timeout_s}s: {' '.join(args)}"
            ) from exc
        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip() or "unknown v4l2-ctl error"
            raise SensorControllerError(
                f"v4l2-ctl failed (rc={proc.returncode}): {msg}"
            )
        return proc.stdout


# ---------- helpers --------------------------------------------------------

_CTRL_LINE_RE = re.compile(r"^\s*(\w+):\s*(.+)\s*$")


def _parse_control_dump(text: str) -> dict[str, str]:
    """Parse the output of ``v4l2-ctl -C ctrl1,ctrl2,...`` into a dict."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _CTRL_LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


_FOURCC_RE = re.compile(r"Pixel Format\s*:\s*'([A-Za-z0-9 ]{4})'")


def _extract_fourcc(text: str) -> str | None:
    m = _FOURCC_RE.search(text)
    return m.group(1).strip() if m else None


def _current_user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def read_sensor_name(
    subdev: str = DEFAULT_SENSOR_SUBDEV,
    *,
    v4l2_ctl_binary: str = "v4l2-ctl",
    run_as_user: str | None = "notavis",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> str:
    """Read the VC driver's ``sensor_name`` control from ``subdev``.

    Returns the raw string reported by the driver (e.g. ``"OV9281"``).
    Raises :class:`SensorControllerError` if the subdev is missing or the
    control cannot be read.
    """
    argv: list[str] = []
    if run_as_user and run_as_user != _current_user():
        argv.extend(["sudo", "-n", "-u", run_as_user])
    argv.extend([v4l2_ctl_binary, "-d", subdev, "-C", "sensor_name"])
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        raise SensorControllerError(f"v4l2-ctl binary not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SensorControllerError(
            f"v4l2-ctl timed out after {timeout_s}s reading sensor_name"
        ) from exc
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown v4l2-ctl error"
        raise SensorControllerError(
            f"could not read sensor_name from {subdev}: {msg}"
        )
    controls = _parse_control_dump(proc.stdout)
    name = controls.get("sensor_name", "").strip()
    if not name:
        raise SensorControllerError(
            f"sensor_name control on {subdev} returned empty value; "
            f"is the VC MIPI driver bound?"
        )
    return name


def discover_sensor_profile(
    subdev: str = DEFAULT_SENSOR_SUBDEV,
    *,
    v4l2_ctl_binary: str = "v4l2-ctl",
    run_as_user: str | None = "notavis",
) -> SensorProfile:
    """Read ``sensor_name`` from ``subdev`` and load the matching profile.

    Raises :class:`SensorControllerError` if the subdev cannot be read and
    :class:`~.sensor_profiles_loader.UnknownSensorError` if the sensor is
    detected but not in the registry.

    Retained for backwards compatibility. New callers should prefer
    :func:`discover_sensor`, which additionally falls back to the catalog
    registry when no live profile exists.
    """
    name = read_sensor_name(
        subdev,
        v4l2_ctl_binary=v4l2_ctl_binary,
        run_as_user=run_as_user,
    )
    return load_profile(name)


DiscoveryStatus = str  # "live" | "catalog" | "unknown"


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of :func:`discover_sensor`.

    ``status`` is one of:

    * ``"live"`` — a live-verified :class:`SensorProfile` was loaded from
      ``sensor_profiles/``; ``profile`` is set, ``catalog`` may be set if a
      catalog entry with the same ``sensor_name`` also exists.
    * ``"catalog"`` — no live profile is registered, but a catalog entry
      exists under ``sensor_profiles/catalog/``; ``catalog`` is set,
      ``profile`` is ``None``. Controls that require runtime values
      (mediabus code, fourcc mapping, control bounds) are not available.
    * ``"unknown"`` — the sensor is neither in the live registry nor in
      the catalog. ``sensor_name`` still carries the raw driver string so
      the UI can prompt the user to add a YAML.
    """

    status: DiscoveryStatus
    sensor_name: str
    profile: SensorProfile | None = None
    catalog: CatalogEntry | None = None

    @property
    def is_live(self) -> bool:
        return self.status == "live"

    @property
    def is_catalog_only(self) -> bool:
        return self.status == "catalog"

    @property
    def is_unknown(self) -> bool:
        return self.status == "unknown"


def discover_sensor(
    subdev: str = DEFAULT_SENSOR_SUBDEV,
    *,
    v4l2_ctl_binary: str = "v4l2-ctl",
    run_as_user: str | None = "notavis",
) -> DiscoveryResult:
    """Read ``sensor_name`` from ``subdev`` and resolve it against the registry.

    Detection order:

    1. Live profile in ``sensor_profiles/`` (via :func:`load_profile`).
    2. Catalog entry in ``sensor_profiles/catalog/`` (via
       :func:`load_catalog_entry`).
    3. Neither — status ``"unknown"``.

    Raises :class:`SensorControllerError` only if the subdev itself cannot
    be read. A sensor that is present but not in either registry does
    **not** raise; the caller decides how to surface that state.
    """
    name = read_sensor_name(
        subdev,
        v4l2_ctl_binary=v4l2_ctl_binary,
        run_as_user=run_as_user,
    )

    # 1. Try live profile.
    profile: SensorProfile | None = None
    try:
        profile = load_profile(name)
    except UnknownSensorError:
        profile = None

    # 2. Try catalog entry (independent of profile presence, so a live
    # profile with a matching catalog entry keeps both for the UI).
    catalog: CatalogEntry | None = None
    try:
        catalog = load_catalog_entry(name)
    except UnknownCatalogSensorError:
        catalog = None

    if profile is not None:
        return DiscoveryResult(
            status="live", sensor_name=name, profile=profile, catalog=catalog,
        )
    if catalog is not None:
        return DiscoveryResult(
            status="catalog", sensor_name=name, profile=None, catalog=catalog,
        )
    return DiscoveryResult(
        status="unknown", sensor_name=name, profile=None, catalog=None,
    )


__all__ = [
    "DEFAULT_SENSOR_SUBDEV",
    "DEFAULT_VIDEO_DEVICE",
    "DiscoveryResult",
    "DiscoveryStatus",
    "SensorController",
    "SensorControllerError",
    "SensorSnapshot",
    "discover_sensor",
    "discover_sensor_profile",
    "read_sensor_name",
]
