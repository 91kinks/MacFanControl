"""
override.py
MacFanControl - Shared override file interface.

Both menubar.py (writer) and daemon.py (reader) use these functions
to communicate user intent through override.json.

Override file lives next to this module in the project root.
Format:
    {"mode": "auto"}
    {"mode": "manual", "rpm": 4000}
    {"mode": "max"}

Modes:
    auto   — daemon runs the fan curve normally (default)
    manual — daemon holds both fans at the specified RPM
    max    — daemon holds both fans at hardware maximum
"""

import json
import os

OVERRIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "override.json")


def read_override() -> dict:
    """
    Read the current override state.
    Returns {"mode": "auto"} if file is missing or unreadable.
    Never raises — always returns a safe default.
    """
    try:
        with open(OVERRIDE_PATH) as f:
            data = json.load(f)
        if data.get("mode") in ("auto", "manual", "max"):
            return data
    except Exception:
        pass
    return {"mode": "auto"}


def write_override(mode: str, rpm: int | None = None) -> bool:
    """
    Write a new override state.
    Returns True on success, False on failure.

    Args:
        mode: "auto", "manual", or "max"
        rpm:  target RPM for manual mode (ignored for auto/max)
    """
    try:
        data: dict = {"mode": mode}
        if mode == "manual" and rpm is not None:
            data["rpm"] = int(rpm)
        with open(OVERRIDE_PATH, "w") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False


def clear_override() -> bool:
    """Reset to auto mode."""
    return write_override("auto")