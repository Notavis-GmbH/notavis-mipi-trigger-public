"""Sensor profile registry.

Each YAML file under this package describes one VC MIPI sensor: its native
frame size, supported pixel formats, and V4L2 control bounds. The registry
key is the exact string returned by the VC driver's ``sensor_name`` V4L2
control on the sensor subdev.

See :mod:`vc_trigger.sensor_profiles_loader` for the loader API.
"""

from __future__ import annotations
