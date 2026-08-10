"""Parameter models for the trigger controller.

All bounds are enforced here, at the boundary between UI and hardware. The
controller trusts validated model instances and does not re-check numeric
ranges.

Hard limits:

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
