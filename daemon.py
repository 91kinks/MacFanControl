"""
daemon.py
MacFanControl - Main fan control daemon.

Reads target sensor temperature every N seconds, computes target RPM for
each fan using the curve in fan_curve.py, and calls the macfan_smc binary
to apply. Also monitors CPU_Speed_Limit via a background thread that listens
to pmset -g thermlog and reacts instantly to any change.

Safety behaviors:
    - Sensor read failure                      -> restore auto control and exit
    - Target sensor >= emergency_temp          -> override to max RPM immediately
    - CPU_Speed_Limit <= speed_limit_emergency -> restore auto and exit
    - CPU_Speed_Limit <  speed_limit_warn      -> force max RPM, reset cooldown
    - Fans hold current RPM until cooldown_seconds elapses at safe temp
      AND CPU_Speed_Limit is healthy
    - SIGINT / SIGTERM                         -> restore auto control and exit cleanly

Usage:
    sudo python3 daemon.py
    sudo python3 daemon.py --config /path/to/config.json
    sudo python3 daemon.py --dry-run   (read-only, prints what it would do)
"""

import argparse
import json
import os
import signal
import sys
import time

from sensors import read_gpu_temp, read_cpu_temp, set_rpm, set_auto
from fan_curve import calc_rpm
from speed_watcher import SpeedLimitWatcher


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    if not os.path.isfile(path):
        print(f"ERROR: config file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid config JSON: {e}")
            sys.exit(1)


def resolve_binary(config: dict, config_path: str) -> str:
    """Resolve binary path relative to config file location."""
    binary = config.get("binary", "native/macfan_smc")
    if not os.path.isabs(binary):
        base = os.path.dirname(os.path.abspath(config_path))
        binary = os.path.join(base, binary)
    binary = os.path.normpath(binary)
    if not os.path.isfile(binary):
        print(f"ERROR: binary not found: {binary}")
        print("       Build it first:  cd native && make")
        sys.exit(1)
    return binary


# ---------------------------------------------------------------------------
# Daemon state
# ---------------------------------------------------------------------------

class FanDaemon:
    def __init__(self, config: dict, binary: str, dry_run: bool = False):
        self.binary   = binary
        self.dry_run  = dry_run

        # Sensor keys
        self.gpu_key    = config["sensor"]["gpu_temp_key"]
        self.cpu_key    = config["sensor"]["cpu_temp_key"]
        self.target_key = config["sensor"]["target_sensor_key"]  # "cpu" or "gpu"

        # Per-fan config
        self.floor0 = config["fan0"]["floor_rpm"]
        self.max0   = config["fan0"]["max_rpm"]
        self.floor1 = config["fan1"]["floor_rpm"]
        self.max1   = config["fan1"]["max_rpm"]

        # Curve config
        self.start_temp       = config["curve"]["start_temp"]
        self.max_temp         = config["curve"]["max_temp"]
        self.hysteresis       = config["curve"]["hysteresis"]
        self.exponent         = config["curve"].get("exponent", 1.0)
        self.cooldown_seconds = config["curve"].get("cooldown_seconds", 60)

        # Safety config
        self.emergency             = config["safety"]["emergency_temp"]
        self.speed_limit_warn      = config["safety"].get("speed_limit_warn", 70)
        self.speed_limit_emergency = config["safety"].get("speed_limit_emergency", 60)

        # Poll interval
        self.interval = config.get("poll_interval_seconds", 3)

        # Runtime state
        self.ramping0  = False
        self.ramping1  = False
        self.last_rpm0 = -1
        self.last_rpm1 = -1

        # Cooldown timer — timestamp when temp first entered the safe zone, or None.
        # Fans won't ramp down until cooldown_seconds have elapsed here AND
        # CPU_Speed_Limit is healthy.
        self._cool_since: float | None = None

        # Log threshold
        self.log_threshold = config.get("log_threshold_temp", 80)

        # Background speed limit watcher — started here, stopped on shutdown
        self._watcher = SpeedLimitWatcher()

    def restore_auto(self):
        """Hand control back to Apple. Always called on exit."""
        self._watcher.stop()
        if self.dry_run:
            print("[dry-run] set-auto")
            return
        ok = set_auto(self.binary)
        if ok:
            print("Fans restored to auto control.")
        else:
            print("WARNING: could not restore auto control. Reboot to reset fans.")

    def apply_rpm(self, rpm0: int, rpm1: int):
        """Write RPM targets, skipping if unchanged from last write."""
        if rpm0 == self.last_rpm0 and rpm1 == self.last_rpm1:
            return

        if self.dry_run:
            print(f"[dry-run] set-rpm {rpm0} {rpm1}")
            self.last_rpm0 = rpm0
            self.last_rpm1 = rpm1
            return

        ok = set_rpm(self.binary, rpm0, rpm1)
        if ok:
            self.last_rpm0 = rpm0
            self.last_rpm1 = rpm1
        else:
            print("WARNING: set-rpm failed")

    def _cooldown_cleared(self, speed_limit: int | None) -> bool:
        """
        Returns True only when both conditions are met:
          1. Temp has been in the safe zone for at least cooldown_seconds
          2. CPU_Speed_Limit is healthy (>= speed_limit_warn), or still None
             (None = watcher hasn't received a reading yet — give benefit of doubt)

        If either condition fails the fans hold their current RPM.
        """
        if speed_limit is not None and speed_limit < self.speed_limit_warn:
            self._cool_since = None  # reset — not safe to ramp down yet
            return False

        if self._cool_since is None:
            return False

        return (time.monotonic() - self._cool_since) >= self.cooldown_seconds

    def tick(self) -> bool:
        """
        Single poll cycle.
        Returns False if the daemon should stop (sensor failure).
        """
        gpu = read_gpu_temp(self.binary, self.gpu_key)
        cpu = read_cpu_temp(self.binary, self.cpu_key)

        # Resolve which sensor drives the fan curve based on config target_sensor_key
        sensor_map = {"gpu": gpu, "cpu": cpu}
        target_sensor = sensor_map.get(self.target_key.lower())

        if target_sensor is None:
            print("ERROR: Target sensor temperature read failed. Restoring auto control.")
            self.restore_auto()
            return False

        # Pull the latest speed limit from the background watcher — instant, no I/O
        speed_limit = self._watcher.get()

        # --- Speed limit emergency ---
        # Deep into throttling — hand off to Apple immediately. Apple's auto fans
        # recover faster at this point than our curve can.
        if speed_limit is not None and speed_limit <= self.speed_limit_emergency:
            print(f"EMERGENCY: CPU_Speed_Limit {speed_limit}% <= {self.speed_limit_emergency}% "
                  f"— restoring auto control")
            self.restore_auto()
            return False

        # --- Speed limit warning ---
        # Degrading but not critical. Blast fans to max and freeze the cooldown
        # timer so we don't ramp back down while the system is still stressed.
        if speed_limit is not None and speed_limit < self.speed_limit_warn:
            print(f"WARNING: CPU_Speed_Limit {speed_limit}% < {self.speed_limit_warn}% "
                  f"— forcing max fan speed")
            self.apply_rpm(self.max0, self.max1)
            self.ramping0     = True
            self.ramping1     = True
            self._cool_since  = None
            return True

        # --- Temperature emergency ---
        if target_sensor >= self.emergency:
            print(f"EMERGENCY: Target Sensor {target_sensor:.1f}C >= {self.emergency}C "
                  f"— max fan speed")
            self.apply_rpm(self.max0, self.max1)
            self.ramping0     = True
            self.ramping1     = True
            self._cool_since  = None
            return True

        # --- Cooldown tracking ---
        # Mirror the hysteresis threshold used in calc_rpm so both stay in sync.
        lower_threshold = (self.start_temp - self.hysteresis) \
                          if (self.ramping0 or self.ramping1) else self.start_temp

        if target_sensor < lower_threshold:
            if self._cool_since is None:
                self._cool_since = time.monotonic()  # start the clock
        else:
            self._cool_since = None  # still warm — reset

        # --- Fan curve calculation ---
        # Hold current RPM if we're in an active ramp and cooldown hasn't cleared.
        currently_ramping = self.ramping0 or self.ramping1
        cooldown_done     = self._cooldown_cleared(speed_limit)

        if currently_ramping and not cooldown_done:
            elapsed   = (time.monotonic() - self._cool_since) if self._cool_since else 0
            remaining = max(0, self.cooldown_seconds - elapsed)
            if target_sensor >= self.log_threshold:
                gpu_str = f"  GPU {gpu:.1f}C" if gpu is not None else ""
                spd_str = f"  SPD {speed_limit}%" if speed_limit is not None else ""
                print(f"Target {target_sensor:.1f}C{gpu_str}{spd_str}  "
                      f"holding — cooldown {remaining:.0f}s remaining")
            return True

        # Cooldown cleared (or fans were already at floor) — run the curve normally
        rpm0 = calc_rpm(target_sensor, self.floor0, self.max0,
                        self.start_temp, self.max_temp,
                        self.hysteresis, self.ramping0, self.exponent)

        rpm1 = calc_rpm(target_sensor, self.floor1, self.max1,
                        self.start_temp, self.max_temp,
                        self.hysteresis, self.ramping1, self.exponent)

        self.ramping0 = rpm0 > self.floor0
        self.ramping1 = rpm1 > self.floor1

        if not self.ramping0 and not self.ramping1:
            self._cool_since = None

        self.apply_rpm(rpm0, rpm1)

        # Status line — only log above threshold to keep the log file manageable
        if target_sensor >= self.log_threshold:
            gpu_str = f"  GPU {gpu:.1f}C" if gpu is not None else ""
            spd_str = f"  SPD {speed_limit}%" if speed_limit is not None else ""
            print(f"Target {target_sensor:.1f}C{gpu_str}{spd_str}  "
                  f"->  Fan0 {rpm0} RPM  Fan1 {rpm1} RPM")

        return True

    def run(self):
        """Main daemon loop."""
        target_smc = self.cpu_key if self.target_key == "cpu" else self.gpu_key
        print("MacFanControl daemon starting.")
        print(f"  Target sensor : {self.target_key.upper()} ({target_smc})  (control)")
        print(f"  GPU sensor    : {self.gpu_key}  (display)")
        print(f"  CPU sensor    : {self.cpu_key}  (display)")
        print(f"  Curve         : {self.start_temp}C - {self.max_temp}C")
        print(f"  Fan0 range    : {self.floor0} - {self.max0} RPM")
        print(f"  Fan1 range    : {self.floor1} - {self.max1} RPM")
        print(f"  Cooldown      : {self.cooldown_seconds}s")
        print(f"  SPD warn      : {self.speed_limit_warn}%")
        print(f"  SPD emergency : {self.speed_limit_emergency}%")
        print(f"  Interval      : {self.interval}s")
        print(f"  Speed watcher : live (pmset thermlog thread)")
        if self.dry_run:
            print(f"  Mode          : DRY RUN (no writes)")
        print()

        while True:
            ok = self.tick()
            if not ok:
                sys.exit(1)
            time.sleep(self.interval)


# ---------------------------------------------------------------------------
# Signal handlers — restore auto on SIGINT / SIGTERM
# ---------------------------------------------------------------------------

_daemon_instance = None

def _handle_signal(signum, frame):
    print(f"\nSignal {signum} received. Shutting down.")
    if _daemon_instance is not None:
        _daemon_instance.restore_auto()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _daemon_instance

    parser = argparse.ArgumentParser(description="MacFanControl daemon")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config.json"),
        help="Path to config.json (default: config.json next to daemon.py)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read sensors and print targets without writing to SMC"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    binary = resolve_binary(config, args.config)

    daemon = FanDaemon(config, binary, dry_run=args.dry_run)
    _daemon_instance = daemon

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    daemon.run()


if __name__ == "__main__":
    main()