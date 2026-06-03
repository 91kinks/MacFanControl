#!/Users/koryinks/MacFanControl/venv/bin/python3
"""
menubar.py
MacFanControl - Menu bar status display.

READ-ONLY. Does not write to the SMC or interfere with the daemon.
The daemon (daemon.py) handles all fan control.
This app just displays current sensor and fan state in the menu bar.

Displays in menu bar title:
    GPU 62°C  ↑2600

Menu items show:
    GPU: 62.3°C
    CPU: 58.1°C
    ─────────────
    Fan 0 (Left):   2600 RPM  [auto]
    Fan 1 (Right):  2600 RPM  [auto]
    ─────────────
    Daemon: running
    ─────────────
    Quit

Usage:
    Run from the project root (daemon should already be running):
    /Users/koryinks/MacFanControl/venv/bin/python3 menubar.py
"""

import json
import os
import subprocess
import sys

import rumps

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
        # Start with a placeholder title while first read happens
        super().__init__("MacFanControl", title="🌡 --°C")

        self.config = config
        self.binary = binary
        self.gpu_key = config["sensor"]["gpu_temp_key"]
        self.cpu_key = config["sensor"]["cpu_temp_key"]

        # Build static menu structure
        # rumps.separator is a divider line
        self.gpu_item    = rumps.MenuItem("GPU: --")
        self.cpu_item    = rumps.MenuItem("CPU: --")
        self.fan0_item   = rumps.MenuItem("Fan 0: --")
        self.fan1_item   = rumps.MenuItem("Fan 1: --")
        self.daemon_item = rumps.MenuItem("Daemon: checking...")

        self.menu = [
            self.gpu_item,
            self.cpu_item,
            rumps.separator,
            self.fan0_item,
            self.fan1_item,
            rumps.separator,
            self.daemon_item,
            rumps.separator,
            rumps.MenuItem("Quit", callback=self.quit_app)
        ]

        # Start the refresh timer
        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()

        # Do an immediate first read
        self.refresh(None)

    def refresh(self, _):
        """Called every REFRESH_SECONDS to update all display values."""
        temps = read_temps(self.binary)
        fans  = read_fans(self.binary)

        gpu = temps.get(self.gpu_key)
        cpu = temps.get(self.cpu_key)

        # Update menu items
        self.gpu_item.title = f"GPU: {gpu:.1f}°C" if gpu is not None else "GPU: --"
        self.cpu_item.title = f"CPU: {cpu:.1f}°C" if cpu is not None else "CPU: --"

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
        # Shows GPU temp and fan 0 actual RPM as a quick glance
        if gpu is not None:
            fan_rpm = fans[0]["actual"] if fans else 0
            self.title = f"GPU {gpu:.0f}°C  ↑{fan_rpm}"
        else:
            self.title = "GPU --°C"

    def quit_app(self, _):
        """Clean exit — just quit the menu bar app. Daemon keeps running."""
        rumps.quit_application()


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