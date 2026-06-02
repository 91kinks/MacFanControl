"""
fan_curve.py
MacFanControl - Fan curve calculation.

Computes target RPM for each fan based on GPU temperature.
All curve logic lives here, isolated from the daemon loop.

Curve behavior:
    - Below start_temp:               hold at floor_rpm
    - start_temp to max_temp:         linear ramp floor_rpm -> max_rpm
    - At or above max_temp:           max_rpm (emergency handled by daemon)
    - Hysteresis:                     ramp-down only starts at start_temp - hysteresis

Each fan scales independently against its own floor and max RPM.
"""


def calc_rpm(
    temp: float,
    floor_rpm: int,
    max_rpm: int,
    start_temp: float,
    max_temp: float,
    hysteresis: float,
    ramping_up: bool
) -> int:
    """
    Calculate target RPM for a single fan given current GPU temperature.

    Args:
        temp:        current GPU temperature in celsius
        floor_rpm:   minimum RPM to hold below the curve start
        max_rpm:     maximum RPM at or above max_temp
        start_temp:  temperature at which the ramp begins
        max_temp:    temperature at which max_rpm is reached
        hysteresis:  degrees below start_temp before ramp-down begins
        ramping_up:  True if fan is currently in active ramp (affects hysteresis)

    Returns:
        target RPM as int, clamped to [floor_rpm, max_rpm]
    """

    # Emergency ceiling — daemon handles the override, but clamp here too
    if temp >= max_temp:
        return max_rpm

    # Determine the effective lower threshold with hysteresis.
    # If we're currently ramping, don't start coming down until
    # temp drops below (start_temp - hysteresis).
    if ramping_up:
        lower_threshold = start_temp - hysteresis
    else:
        lower_threshold = start_temp

    # Below the curve — hold at floor
    if temp < lower_threshold:
        return floor_rpm

    # Inside the ramp — linear interpolation
    # At start_temp -> floor_rpm, at max_temp -> max_rpm
    ratio = (temp - start_temp) / (max_temp - start_temp)
    ratio = max(0.0, min(1.0, ratio))   # clamp to [0, 1]

    rpm = floor_rpm + ratio * (max_rpm - floor_rpm)

    # Round to nearest 50 RPM to avoid constant micro-adjustments
    rpm = round(rpm / 50) * 50

    return int(max(floor_rpm, min(max_rpm, rpm)))