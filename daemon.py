"""
daemon.py
MacFanControl - Main fan control daemon.

Reads GPU temperature every N seconds, computes target RPM for each fan
using the curve in fan_curve.py, and calls the macfan_smc binary to apply.

Safety behaviors:
    - Sensor read failure  -> restore auto control and exit
    - GPU >= emergency_temp -> override to max RPM immediately
    - SIGINT / SIGTERM     -> restore auto control and exit cleanly

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
        self.binary       = binary
        self.dry_run      = dry_run

        # Sensor keys
        self.gpu_key      = config["sensor"]["gpu_temp_key"]
        self.cpu_key      = config["sensor"]["cpu_temp_key"]

        # Per-fan config
        self.floor0       = config["fan0"]["floor_rpm"]
        self.max0         = config["fan0"]["max_rpm"]
        self.floor1       = config["fan1"]["floor_rpm"]
        self.max1         = config["fan1"]["max_rpm"]

        # Curve config
        self.start_temp   = config["curve"]["start_temp"]
        self.max_temp     = config["curve"]["max_temp"]
        self.hysteresis   = config["curve"]["hysteresis"]

        # Safety config
        self.emergency    = config["safety"]["emergency_temp"]

        # Poll interval
        self.interval     = config.get("poll_interval_seconds", 3)

        # Runtime state - track whether each fan is in active ramp
        # for hysteresis calculation
        self.ramping0     = False
        self.ramping1     = False

        # Track last targets to avoid unnecessary writes
        self.last_rpm0    = -1
        self.last_rpm1    = -1

        # Log threshold
        self.log_threshold = config.get("log_threshold_temp", 80)  # Only log when GPU >= threshold

    def restore_auto(self):
        """Hand control back to Apple. Always called on exit."""
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
            return  # No change, skip the write

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

    def tick(self) -> bool:
        """
        Single poll cycle.
        Returns False if the daemon should stop (sensor failure).
        """
        gpu = read_gpu_temp(self.binary, self.gpu_key)
        cpu = read_cpu_temp(self.binary, self.cpu_key)

        if gpu is None:
            print("ERROR: GPU temperature read failed. Restoring auto control.")
            self.restore_auto()
            return False

        # Emergency override — GPU too hot, go to max immediately
        if gpu >= self.emergency:
            print(f"EMERGENCY: GPU {gpu:.1f}C >= {self.emergency}C — max fan speed")
            self.apply_rpm(self.max0, self.max1)
            self.ramping0 = True
            self.ramping1 = True
            return True

        # Calculate target RPM for each fan independently
        rpm0 = calc_rpm(gpu, self.floor0, self.max0,
                        self.start_temp, self.max_temp,
                        self.hysteresis, self.ramping0)

        rpm1 = calc_rpm(gpu, self.floor1, self.max1,
                        self.start_temp, self.max_temp,
                        self.hysteresis, self.ramping1)

        # Update ramp state for hysteresis next tick
        self.ramping0 = rpm0 > self.floor0
        self.ramping1 = rpm1 > self.floor1

        # Apply
        self.apply_rpm(rpm0, rpm1)

        # Status line
        cpu_str = f"  CPU {cpu:.1f}C" if cpu is not None else ""
        if gpu >= self.emergency:
            print(f"GPU {gpu:.1f}C{cpu_str} >= {self.emergency}C  ->  EMERGENCY MAX FAN")

        return True

    def run(self):
        """Main daemon loop."""
        print(f"MacFanControl daemon starting.")
        print(f"  GPU sensor : {self.gpu_key}")
        print(f"  Curve      : {self.start_temp}C - {self.max_temp}C")
        print(f"  Fan0 range : {self.floor0} - {self.max0} RPM")
        print(f"  Fan1 range : {self.floor1} - {self.max1} RPM")
        print(f"  Interval   : {self.interval}s")
        if self.dry_run:
            print(f"  Mode       : DRY RUN (no writes)")
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