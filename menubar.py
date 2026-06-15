"""
menubar.py
MacFanControl - Menu bar status display and manual override control.

Displays current sensor and fan state in the menu bar.
Allows user to set fan mode (Auto / Manual / Max) via the dropdown.
Writes override.json — the daemon reads this on every tick.

Displays in menu bar title (normal):
    62°C  ↑2600  100%

Displays in menu bar title (speed limit warning):
    ⚠ 72°C  ↑3200  65%

Menu structure:
    62.3°C  (TC0F — control sensor)
    GPU (TG0D): 58.1°C
    CPU Speed: 100%
    ─────────────
    Fan 0 (Left Fan):   2600 RPM  [auto]
    Fan 1 (Right Fan):  2600 RPM  [auto]
    ─────────────
    Mode: ● Auto
      → Set Auto
      → Set Max
    Manual RPM: 4000
      [ – 500 ]  [ – 100 ]  [ + 100 ]  [ + 500 ]
      [ Enter RPM... ]
    ─────────────
    Daemon: ● running
      → Start Daemon
      → Stop Daemon
    ─────────────
    Quit

Usage:
    /Users/USERNAME/MacFanControl/venv/bin/python3 menubar.py
"""

import json
import os
import subprocess
import sys

import rumps
import AppKit

from sensors import read_cpu_speed_limit
from override import read_override, write_override, OVERRIDE_PATH

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DAEMON_PLIST    = os.path.expanduser("~/Library/LaunchAgents/com.macfancontrol.daemon.plist")
REFRESH_SECONDS = 3
MANUAL_RPM_MIN = 2600
MANUAL_RPM_MAX = 6156


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

        self.config  = config
        self.binary  = binary
        self.gpu_key    = config["sensor"]["gpu_temp_key"]
        self.cpu_key    = config["sensor"]["cpu_temp_key"]
        self.target_key = config["sensor"]["target_sensor_key"]  # "cpu" or "gpu"

        # Speed limit threshold for title bar warning (mirrors daemon config)
        self.speed_limit_warn = config["safety"].get("speed_limit_warn", 70)

        # Floor/max from config — used to clamp manual RPM
        self.floor_rpm = min(config["fan0"]["floor_rpm"], config["fan1"]["floor_rpm"])
        self.max_rpm   = max(config["fan0"]["max_rpm"],   config["fan1"]["max_rpm"])

        # Current manual RPM — starts at floor, updated by buttons/dialog
        self._manual_rpm = max(self.floor_rpm, 3000)

        # ---------------------------------------------------------------------------
        # Sensor display items
        # ---------------------------------------------------------------------------
        self.target_item = rumps.MenuItem("Target: --°C")
        self.gpu_item    = rumps.MenuItem("GPU: --°C")
        self.cpu_item    = rumps.MenuItem("CPU: --°C")
        self.speed_item  = rumps.MenuItem("CPU Speed: --%")

        # ---------------------------------------------------------------------------
        # Fan display items
        # ---------------------------------------------------------------------------
        self.fan0_item = rumps.MenuItem("Fan 0: --")
        self.fan1_item = rumps.MenuItem("Fan 1: --")

        # ---------------------------------------------------------------------------
        # Mode control items
        # ---------------------------------------------------------------------------
        self.mode_item     = rumps.MenuItem("Mode: ● Auto")
        self.set_auto_item = rumps.MenuItem("  → Set Auto",   callback=self.on_set_auto)
        self.set_max_item  = rumps.MenuItem("  → Set Max",    callback=self.on_set_max)

        # Manual RPM display + adjustment buttons
        self.manual_rpm_item  = rumps.MenuItem(f"Manual RPM: {self._manual_rpm}")
        self.btn_minus500     = rumps.MenuItem("  [ – 500 ]",      callback=self.on_minus500)
        self.btn_minus100     = rumps.MenuItem("  [ – 100 ]",      callback=self.on_minus100)
        self.btn_plus100      = rumps.MenuItem("  [ + 100 ]",      callback=self.on_plus100)
        self.btn_plus500      = rumps.MenuItem("  [ + 500 ]",      callback=self.on_plus500)
        self.btn_enter_rpm    = rumps.MenuItem("  [ Enter RPM... ]", callback=self.on_enter_rpm)
        self.btn_set_manual   = rumps.MenuItem("  → Set Manual",   callback=self.on_set_manual)

        # ---------------------------------------------------------------------------
        # Daemon status + controls
        # ---------------------------------------------------------------------------
        self.daemon_item       = rumps.MenuItem("Daemon: checking...")
        self.daemon_start_item = rumps.MenuItem("  → Start Daemon", callback=self.on_start_daemon)
        self.daemon_stop_item  = rumps.MenuItem("  → Stop Daemon",  callback=self.on_stop_daemon)

        # ---------------------------------------------------------------------------
        # Menu structure
        # ---------------------------------------------------------------------------
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
            self.mode_item,
            self.set_auto_item,
            self.set_max_item,
            self.manual_rpm_item,
            self.btn_minus500,
            self.btn_minus100,
            self.btn_plus100,
            self.btn_plus500,
            self.btn_enter_rpm,
            self.btn_set_manual,
            rumps.separator,
            self.daemon_item,
            self.daemon_start_item,
            self.daemon_stop_item,
            rumps.separator,
        ]

        # Start the refresh timer
        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()

        # Hide from dock once NSApp is ready
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

    # ---------------------------------------------------------------------------
    # Override helpers
    # ---------------------------------------------------------------------------

    def _clamp_rpm(self, rpm: int) -> int:
        return max(self.floor_rpm, min(self.max_rpm, rpm))

    def _apply_manual_rpm(self, rpm: int):
        """Clamp, save, and write manual override."""
        self._manual_rpm = self._clamp_rpm(rpm)
        self.manual_rpm_item.title = f"Manual RPM: {self._manual_rpm}"
        write_override("manual", self._manual_rpm)

    # ---------------------------------------------------------------------------
    # Mode button callbacks
    # ---------------------------------------------------------------------------

    def on_set_auto(self, _):
        write_override("auto")

    def on_set_max(self, _):
        write_override("max")

    def on_set_manual(self, _):
        write_override("manual", self._manual_rpm)

    # ---------------------------------------------------------------------------
    # Daemon control callbacks
    # ---------------------------------------------------------------------------

    def on_start_daemon(self, _):
        """Load the daemon launchd agent."""
        try:
            subprocess.run(["launchctl", "load", DAEMON_PLIST], check=True)
        except Exception as e:
            rumps.alert(title="Start Failed", message=str(e), ok="OK")

    def on_stop_daemon(self, _):
        """Unload the daemon launchd agent and restore auto fan control."""
        try:
            subprocess.run(["launchctl", "unload", DAEMON_PLIST], check=True)
        except Exception as e:
            rumps.alert(title="Stop Failed", message=str(e), ok="OK")

    # ---------------------------------------------------------------------------
    # RPM adjustment callbacks
    # ---------------------------------------------------------------------------

    def on_minus500(self, _):
        self._apply_manual_rpm(self._manual_rpm - 500)

    def on_minus100(self, _):
        self._apply_manual_rpm(self._manual_rpm - 100)

    def on_plus100(self, _):
        self._apply_manual_rpm(self._manual_rpm + 100)

    def on_plus500(self, _):
        self._apply_manual_rpm(self._manual_rpm + 500)

    def on_enter_rpm(self, _):
        """Show a native macOS dialog for direct RPM text input."""
        response = rumps.Window(
            message=f"Enter target RPM ({self.floor_rpm} – {self.max_rpm}):",
            title="Manual Fan RPM",
            default_text=str(self._manual_rpm),
            ok="Set",
            cancel="Cancel",
            dimensions=(200, 24)
        ).run()

        if response.clicked:
            try:
                rpm = int(response.text.strip())
                self._apply_manual_rpm(rpm)
            except ValueError:
                rumps.alert(
                    title="Invalid RPM",
                    message=f"Please enter a whole number between "
                            f"{self.floor_rpm} and {self.max_rpm}.",
                    ok="OK"
                )

    # ---------------------------------------------------------------------------
    # Toggle controls based on daemon state
    # ---------------------------------------------------------------------------
    def _set_daemon_dependent_controls(self, running: bool):
        """
        Enable/disable controls based on whether the daemon is running.
        Manual override controls only matter once the daemon is alive to
        read override.json, so keep them greyed out until then.
        """
        if running:
            self.daemon_start_item.set_callback(None)
            self.daemon_stop_item.set_callback(self.on_stop_daemon)

            self.btn_minus500.set_callback(self.on_minus500)
            self.btn_minus100.set_callback(self.on_minus100)
            self.btn_plus100.set_callback(self.on_plus100)
            self.btn_plus500.set_callback(self.on_plus500)
            self.btn_enter_rpm.set_callback(self.on_enter_rpm)
            self.btn_set_manual.set_callback(self.on_set_manual)
        else:
            self.daemon_start_item.set_callback(self.on_start_daemon)
            self.daemon_stop_item.set_callback(None)

            self.btn_minus500.set_callback(None)
            self.btn_minus100.set_callback(None)
            self.btn_plus100.set_callback(None)
            self.btn_plus500.set_callback(None)
            self.btn_enter_rpm.set_callback(None)
            self.btn_set_manual.set_callback(None)

    # ---------------------------------------------------------------------------
    # Refresh — called every REFRESH_SECONDS
    # ---------------------------------------------------------------------------
    def refresh(self, _):
        """Called every REFRESH_SECONDS to update all display values."""
        temps       = read_temps(self.binary)
        fans        = read_fans(self.binary)
        speed_limit = read_cpu_speed_limit()
        override    = read_override()

        # Resolve sensors
        target_smc = self.cpu_key if self.target_key == "cpu" else self.gpu_key
        gpu        = temps.get(self.gpu_key)
        cpu        = temps.get(self.cpu_key)
        target     = temps.get(target_smc)
        

        # --- Sensor display ---
        self.target_item.title = (
            f"Target ({target_smc}): {target:.1f}°C"
            if target is not None else f"Target ({target_smc}): --"
        )
        self.gpu_item.title = (
            f"GPU ({self.gpu_key}): {gpu:.1f}°C"
            if gpu is not None else f"GPU ({self.gpu_key}): --"
        )
        self.cpu_item.title = (
            f"CPU ({self.cpu_key}): {cpu:.1f}°C" if cpu is not None else f"CPU ({self.cpu_key}): --"
        )

        if speed_limit is not None:
            flag = " ⚠" if speed_limit < self.speed_limit_warn else ""
            self.speed_item.title = f"CPU Speed: {speed_limit}%{flag}"
        else:
            self.speed_item.title = "CPU Speed: --"

        # --- Fan display ---
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

        # --- Mode display ---
        mode = override.get("mode", "auto")
        if mode == "auto":
            self.mode_item.title = "Mode: ● Auto"
        elif mode == "max":
            self.mode_item.title = "Mode: ● Max"
        elif mode == "manual":
            held_rpm = override.get("rpm", self._manual_rpm)
            self.mode_item.title = f"Mode: ● Manual ({held_rpm} RPM)"

        # Keep local manual RPM in sync if another process changed the file
        if mode == "manual" and "rpm" in override:
            self._manual_rpm = override["rpm"]
            self.manual_rpm_item.title = f"Manual RPM: {self._manual_rpm}"

        # --- Daemon status ---
        running = daemon_running()
        self.daemon_item.title = (
            "Daemon: ● running" if running else "Daemon: ○ stopped"
        )
        self.daemon_start_item.title = "  → Start Daemon"
        self.daemon_stop_item.title  = "  → Stop Daemon"
        self._set_daemon_dependent_controls(running)

        # --- Title bar ---
        fan_rpm    = fans[0]["actual"] if fans else 0
        target_str = f"{target:.0f}°C" if target is not None else "--°C"
        spd_str    = f"  {speed_limit}%" if speed_limit is not None else ""

        if speed_limit is not None and speed_limit < self.speed_limit_warn:
            self.title = f"⚠ {target_str}  ↑{fan_rpm}{spd_str}"
        else:
            self.title = f"{target_str}  ↑{fan_rpm}{spd_str}"


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