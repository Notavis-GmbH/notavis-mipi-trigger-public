"""Parameter models for the trigger controller.

All bounds are enforced here, at the boundary between UI and hardware. The
controller trusts validated model instances and does not re-check numeric
ranges.

Hard limits (see AGENTS.md and README):

- Frequency: 1..200 Hz
- Duty cycle: 0..100 %
- Pulse duration: 0.1..1000 ms
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

# --- Hard limits (kept as module-level constants so tests and UI share them) ---

FREQ_MIN_HZ: float = 1.0
FREQ_MAX_HZ: float = 200.0

DUTY_MIN_PCT: float = 0.0
DUTY_MAX_PCT: float = 100.0

PULSE_MIN_MS: float = 0.1
PULSE_MAX_MS: float = 1000.0


class TriggerMode(str, Enum):
    """Operating mode of the trigger controller."""

    IDLE = "idle"
    SINGLE_SHOT = "single_shot"
    PWM = "pwm"


class SingleShotParams(BaseModel):
    """Parameters for a single-shot trigger pulse."""

    pulse_ms: float = Field(
        default=10.0,
        ge=PULSE_MIN_MS,
        le=PULSE_MAX_MS,
        description="Pulse duration in milliseconds.",
    )

    @field_validator("pulse_ms")
    @classmethod
    def _round(cls, v: float) -> float:
        # Avoid float-precision noise in the UI status readout.
        return round(v, 3)


class PwmParams(BaseModel):
    """Parameters for a continuous PWM signal."""

    frequency_hz: float = Field(
        default=100.0,
        ge=FREQ_MIN_HZ,
        le=FREQ_MAX_HZ,
        description="PWM frequency in hertz.",
    )
    duty_cycle_pct: float = Field(
        default=50.0,
        ge=DUTY_MIN_PCT,
        le=DUTY_MAX_PCT,
        description="Duty cycle in percent (0..100).",
    )

    @property
    def duty_cycle_fraction(self) -> float:
        """Duty cycle as a 0..1 fraction (as expected by gpiozero)."""
        return self.duty_cycle_pct / 100.0


# --- Sensor tester (VC MIPI V4L2 bindings) -----------------------------------

EXPOSURE_MIN_US: int = 1
EXPOSURE_MAX_US: int = 1_000_000

GAIN_MIN: int = 0
GAIN_MAX: int = 12_000

SENSOR_TRIGGER_MODE_MIN: int = 0
SENSOR_TRIGGER_MODE_MAX: int = 7


class SensorVendor(str, Enum):
    """Vendor hint for the sensor tester UI.

    The vendor is a UI hint only; the sensor is auto-detected on the board
    via the ``sensor_name`` V4L2 control and does not depend on this field.
    """

    OMNIVISION = "omnivision"
    SONY = "sony"


class SensorPixelFormat(str, Enum):
    """Supported pixel formats for the sensor tester."""

    RAW08 = "raw08"
    RAW10 = "raw10"


class SensorParams(BaseModel):
    """Parameters applied to the VC MIPI sensor subdev.

    Bounds are chosen conservatively; the actual driver bounds may be tighter
    for a given sensor (e.g. exposure max depends on the frame length).
    The controller validates the write against the live V4L2 control range
    and reports the driver-side error verbatim when the value is refused.
    """

    exposure_us: int = Field(
        default=10_000,
        ge=EXPOSURE_MIN_US,
        le=EXPOSURE_MAX_US,
        description="Exposure time in microseconds.",
    )
    gain: int = Field(
        default=0,
        ge=GAIN_MIN,
        le=GAIN_MAX,
        description="Analogue gain (driver units).",
    )
    trigger_mode: int = Field(
        default=0,
        ge=SENSOR_TRIGGER_MODE_MIN,
        le=SENSOR_TRIGGER_MODE_MAX,
        description="VC trigger mode 0..7 (0=STREAM, 1=EXT.EDGE, 2=EXT.PULSE).",
    )
    pixel_format: SensorPixelFormat = Field(
        default=SensorPixelFormat.RAW10,
        description="Pixel format on the V4L2 video device.",
    )
    vendor: SensorVendor = Field(
        default=SensorVendor.OMNIVISION,
        description="UI hint for sensor vendor; not enforced against hardware.",
    )
