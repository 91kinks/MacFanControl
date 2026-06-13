"""
menubar.py
MacFanControl - Menu bar status display.

READ-ONLY. Does not write to the SMC or interfere with the daemon.
The daemon (daemon.py) handles all fan control.
This app just displays current sensor and fan state in the menu bar.

Displays in menu bar title (normal):
    Target Sensor 62°C  ↑2600
Displays in menu bar title (speed limit warning):
    ⚠ GPU 72°C  SPD 65%
Menu items show:
    GPU: 62.3°C
    Target (TC0F): 58.1°C
    ─────────────
    CPU Speed: 100%
    ─────────────
    Fan 0 (Left):   2600 RPM  [auto]
    Fan 1 (Right):  2600 RPM  [auto]
    ─────────────
    Daemon: running
    ─────────────
    Quit

Usage:
    Run from the project root (daemon should already be running):
    /Users/USERNAME/MacFanControl/venv/bin/python3 menubar.py
"""

import json
import os
import subprocess
import sys

import rumps
import AppKit

from sensors import read_cpu_speed_limit

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
REFRESH_SECONDS = 3


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_binary(config: dict) -> str:
    binary = config.get("binary", "native/macfan_smc")
    if not os.path.isabs(binary):
        base = os.path.dirname(os.path.abspath(__file__))
        binary = os.path.join(base, binary)
    return os.path.normpath(binary)


# ---------------------------------------------------------------------------
# SMC reads (read-only, no sudo needed)
# ---------------------------------------------------------------------------

def run_binary(binary: str, command: str) -> list[str]:
    """Run macfan_smc and return output lines. Returns [] on failure."""
    try:
        result = subprocess.run(
            [binary, command],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return []
        return result.stdout.strip().splitlines()
    except Exception:
        return []


def read_temps(binary: str) -> dict[str, float]:
    """Returns dict of {key: celsius}."""
    temps = {}
    for line in run_binary(binary, "temps"):
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                temps[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return temps


def read_fans(binary: str) -> list[dict]:
    """Returns list of fan dicts."""
    fans = []
    current = None
    for line in run_binary(binary, "fans"):
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        tag = parts[0]
        val = parts[1] if len(parts) > 1 else ""

        if tag == "FAN":
            if current is not None:
                fans.append(current)
            current = {"index": int(val), "id": "?",
                       "actual": -1, "target": -1, "mode": "?"}
        elif current is not None:
            if tag == "ID":
                current["id"] = val.strip()
            elif tag == "ACTUAL":
                current["actual"] = int(float(val))
            elif tag == "TARGET":
                current["target"] = int(float(val))
            elif tag == "MODE":
                current["mode"] = val.strip()

    if current is not None:
        fans.append(current)
    return fans


def daemon_running() -> bool:
    """Check if the daemon process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "daemon.py"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Menu bar app
# ---------------------------------------------------------------------------

class MacFanControlApp(rumps.App):

    def __init__(self, config: dict, binary: str):
        super().__init__("MacFanControl", title="🌡 --°C")

        self._dock_hidden = False

        self.config = config
        self.binary = binary
        self.gpu_key = config["sensor"]["gpu_temp_key"]
        self.cpu_key = config["sensor"]["cpu_temp_key"]
        self.target_key = config["sensor"]["target_sensor_key"] # "cpu" or "gpu"

        # Speed limit threshold for title bar warning (mirrors daemon config)
        self.speed_limit_warn = config["safety"].get("speed_limit_warn", 70)

        # Build static menu structure
        self.target_item = rumps.MenuItem("Target: --°C")
        self.speed_item  = rumps.MenuItem("CPU Speed: --%")
        self.gpu_item    = rumps.MenuItem("GPU: --")
        self.cpu_item    = rumps.MenuItem("CPU: --")
        self.fan0_item   = rumps.MenuItem("Fan 0: --")
        self.fan1_item   = rumps.MenuItem("Fan 1: --")
        self.daemon_item = rumps.MenuItem("Daemon: checking...")

        self.menu = [
            self.target_item,
            self.speed_item,
            rumps.separator,
            self.gpu_item,
            self.cpu_item,
            rumps.separator,
            self.fan0_item,
            self.fan1_item,
            rumps.separator,
            self.daemon_item,
            rumps.separator
        ]

        # Start the refresh timer
        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()

        self._hide_timer = rumps.Timer(self._hide_from_dock, 0.1)
        self._hide_timer.start()

        # Do an immediate first read
        self.refresh(None)

    def _hide_from_dock(self, _):
        """Hide from dock after NSApp is initialized. Fires once on startup."""
        self._hide_timer.stop()
        AppKit.NSApp.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )

    def refresh(self, _):
        """Called every REFRESH_SECONDS to update all display values."""
        temps = read_temps(self.binary)
        fans  = read_fans(self.binary)
        speed_limit = read_cpu_speed_limit()

        gpu = temps.get(self.gpu_key)
        cpu = temps.get(self.cpu_key)
        target = temps.get(self.cpu_key if self.target_key == "cpu" else self.gpu_key)

        # Determine the display label for the target sensor key string
        target_smc_key = self.cpu_key if self.target_key == "cpu" else self.gpu_key
        # Update menu items
        self.gpu_item.title = (
            f"GPU ({self.gpu_key}): {gpu:.1f}°C" if gpu is not None else f"GPU ({self.gpu_key}): --"
        )
        self.cpu_item.title = (
            f"CPU ({self.cpu_key}): {cpu:.1f}°C" if cpu is not None else f"CPU ({self.cpu_key}): --"
        )
        self.target_item.title = (
            f"Target ({target_smc_key}): {target:.1f}°C"
            if target is not None
            else f"Target ({target_smc_key}): --"
        )

        if speed_limit is not None:
            warn = speed_limit < self.speed_limit_warn
            flag = " ⚠" if warn else ""
            self.speed_item.title = f"CPU Speed: {speed_limit}%{flag}"
        else:
            self.speed_item.title = "CPU Speed: --"

        if len(fans) >= 1:
            f0 = fans[0]
            self.fan0_item.title = (
                f"Fan 0 ({f0['id']}):  {f0['actual']} RPM  [{f0['mode']}]"
            )
        else:
            self.fan0_item.title = "Fan 0: --"

        if len(fans) >= 2:
            f1 = fans[1]
            self.fan1_item.title = (
                f"Fan 1 ({f1['id']}):  {f1['actual']} RPM  [{f1['mode']}]"
            )
        else:
            self.fan1_item.title = "Fan 1: --"

        self.daemon_item.title = (
            "Daemon: ● running" if daemon_running() else "Daemon: ○ not running"
        )

        # Update the menu bar title
        # Shows target_sensor temp and fan 0 actual RPM as a quick glance
        fan_rpm = fans[0]["actual"] if fans else 0
        target_str = f"{target:.0f}°C" if target is not None else f"--°C"
        if speed_limit is not None and speed_limit < self.speed_limit_warn:
            self.title = f"⚠ {target_str}  SPD {speed_limit}%"
        else:
            self.title = f"{target_str}  ↑{fan_rpm} {speed_limit}%"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        config = load_config()
    except Exception as e:
        print(f"ERROR: could not load config: {e}")
        sys.exit(1)

    binary = get_binary(config)
    if not os.path.isfile(binary):
        print(f"ERROR: binary not found: {binary}")
        print("       Build it first:  cd native && make")
        sys.exit(1)

    MacFanControlApp(config, binary).run()