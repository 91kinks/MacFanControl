"""
fan_curve.py
MacFanControl - Fan curve calculation.

Computes target RPM for each fan based on target sensor temperature.
All curve logic lives here, isolated from the daemon loop.

Curve behavior:
    - Below start_temp:               hold at floor_rpm
    - start_temp to max_temp:         exponential ramp floor_rpm -> max_rpm
    - At or above max_temp:           max_rpm (emergency handled by daemon)
    - Hysteresis:                     ramp-down only starts at start_temp - hysteresis

Exponent controls the curve shape:
    exponent < 1.0  — convex curve, fans ramp faster in the lower part of the range
                      (e.g. 0.6 gives noticeably more RPM at 75-80C without being
                      loud at 68C — recommended starting point)
    exponent = 1.0  — linear, identical to previous behavior
    exponent > 1.0  — concave curve, fans stay low then jump hard near max_temp
Each fan scales independently against its own floor and max RPM.
"""


def calc_rpm(
    temp: float,
    floor_rpm: int,
    max_rpm: int,
    start_temp: float,
    max_temp: float,
    hysteresis: float,
    ramping_up: bool,
    exponent: float = 1.0
) -> int:
    """
    Calculate target RPM for a single fan given current target sensor temperature.

    Args:
        temp:        current target sensor temperature in celsius
        floor_rpm:   minimum RPM to hold below the curve start
        max_rpm:     maximum RPM at or above max_temp
        start_temp:  temperature at which the ramp begins
        max_temp:    temperature at which max_rpm is reached
        hysteresis:  degrees below start_temp before ramp-down begins
        ramping_up:  True if fan is currently in active ramp (affects hysteresis)
        exponent:    curve shape (< 1.0 = more aggressive low end, 1.0 = linear,
                     > 1.0 = more aggressive high end). Default 1.0 preserves
                     previous linear behavior if not set in config.

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

    # Inside the ramp — exponential interpolation
    # At start_temp -> floor_rpm, at max_temp -> max_rpm
    ratio = (temp - start_temp) / (max_temp - start_temp)
    ratio = max(0.0, min(1.0, ratio))   # clamp to [0, 1]

    # Apply exponent to shape the curve
    ratio = ratio ** exponent

    rpm = floor_rpm + ratio * (max_rpm - floor_rpm)

    # Round to nearest 50 RPM to avoid constant micro-adjustments
    rpm = round(rpm / 50) * 50

    return int(max(floor_rpm, min(max_rpm, rpm)))