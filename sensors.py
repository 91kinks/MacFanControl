"""
sensors.py
MacFanControl - Subprocess wrapper around the macfan_smc binary.

All communication with the SMC goes through here.
Python never calls IOKit directly.

Public API:
    read_gpu_temp(binary)         -> float | None
    read_cpu_temp(binary)         -> float | None
    read_fans(binary)             -> list[dict] | None
    set_rpm(binary, rpm0, rpm1)   -> bool
    set_auto(binary)              -> bool
    read_cpu_speed_limit()        -> int | None (used by menubar; daemon uses its own thread)
"""

import subprocess


def _run(binary: str, args: list[str], needs_sudo: bool = False) -> tuple[int, str, str]:
    """
    Run the macfan_smc binary with the given arguments.
    Returns (returncode, stdout, stderr).
    """
    cmd = (["sudo"] if needs_sudo else []) + [binary] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _parse_temps(output: str) -> dict[str, float]:
    """
    Parse output of: macfan_smc temps
    Returns dict of {key: celsius}.
    """
    temps = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                temps[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return temps


def read_gpu_temp(binary: str, key: str = "TG0D") -> float | None:
    """
    Read GPU temperature from the SMC.
    Returns celsius as float, or None if the read failed.
    """
    rc, stdout, stderr = _run(binary, ["temps"])
    if rc != 0:
        return None
    temps = _parse_temps(stdout)
    return temps.get(key, None)


def read_cpu_temp(binary: str, key: str = "TC0F") -> float | None:
    """
    Read target sensor temperature from the SMC.
    Returns celsius as float, or None if the read failed.
    """
    rc, stdout, stderr = _run(binary, ["temps"])
    if rc != 0:
        return None
    temps = _parse_temps(stdout)
    return temps.get(key, None)


def read_fans(binary: str) -> list[dict] | None:
    """
    Read all fan info from the SMC.
    Returns list of dicts with keys: index, id, actual, min, max, target, mode.
    Returns None if the read failed.
    """
    rc, stdout, stderr = _run(binary, ["fans"])
    if rc != 0:
        return None

    fans = []
    current = None
    for line in stdout.splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        tag = parts[0]
        val = parts[1] if len(parts) > 1 else ""

        if tag == "FAN":
            if current is not None:
                fans.append(current)
            current = {"index": int(val), "id": "?", "actual": -1,
                       "min": -1, "max": -1, "target": -1, "mode": "?"}
        elif current is not None:
            if tag == "ID":
                current["id"] = val.strip()
            elif tag == "ACTUAL":
                current["actual"] = int(float(val))
            elif tag == "MIN":
                current["min"] = int(float(val))
            elif tag == "MAX":
                current["max"] = int(float(val))
            elif tag == "TARGET":
                current["target"] = int(float(val))
            elif tag == "MODE":
                current["mode"] = val.strip()

    if current is not None:
        fans.append(current)

    return fans if fans else None


def set_rpm(binary: str, rpm0: int, rpm1: int) -> bool:
    """
    Set fan 0 and fan 1 to independent target RPMs in forced mode.
    Returns True on success, False on failure.
    Requires sudo.
    """
    rc, stdout, stderr = _run(binary, ["set-rpm", str(rpm0), str(rpm1)], needs_sudo=True)
    return rc == 0


def set_auto(binary: str) -> bool:
    """
    Return both fans to Apple auto control.
    Returns True on success, False on failure.
    Requires sudo.
    """
    rc, stdout, stderr = _run(binary, ["set-auto"], needs_sudo=True)
    return rc == 0


def read_cpu_speed_limit() -> int | None:
    """
    Read the current CPU_Speed_Limit from `pmset -g therm`.

    Used by the menu bar for its 3-second display refresh.
    The daemon does NOT use this — it has its own SpeedLimitWatcher thread
    that listens to `pmset -g thermlog` and reacts instantly to changes.

    `pmset -g therm` exits immediately with a current snapshot:
        CPU_Scheduler_Limit   = 100
        CPU_Available_CPUs    = 8
        CPU_Speed_Limit       = 100

    Returns the limit as int (0-100), or None if unreadable.
    100 = no throttling. Below 100 = system is throttling the CPU.
    """
    try:
        result = subprocess.run(
            ["pmset", "-g", "therm"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if "CPU_Speed_Limit" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    try:
                        return int(parts[1].strip())
                    except ValueError:
                        pass
        return None

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None