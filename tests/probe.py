#!/usr/bin/env python3
"""
probe.py - MacFanControl Milestone 1: Read all sensors and fan info.

Calls the macfan_smc binary (must be compiled first) and prints a clean
summary of everything the SMC reports. The goal at this stage is purely
to observe — no fan control yet.

Usage:
    python3 tests/probe.py

Expected output (values will vary):
    === Temperatures ===
    TC0P   52.25 C   (CPU proximity)
    TC1C   58.50 C
    TGDD   68.00 C   <-- likely GPU die, AMD R9 M370X
    ...

    === Fans ===
    Fan 0  (Left Fan)
      Actual : 2001 RPM
      Min    : 1299 RPM
      Max    : 6199 RPM
      Safe   : 1299 RPM
      Target : 2001 RPM
      Mode   : auto

Requirements:
    - macfan_smc must be compiled and present at BINARY_PATH below
    - Must be run on macOS (SMC is hardware-specific)
"""

import subprocess
import sys
import os

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Path to the compiled binary, relative to the repo root.
# Adjust if you run probe.py from a different working directory.
BINARY_PATH = os.path.join(
    os.path.dirname(__file__),   # tests/
    "..",                         # repo root
    "native",
    "macfan_smc"
)

# Known temperature key descriptions for MacBookPro11,5.
# We annotate what we know; unknown keys are shown without a label.
# This will grow as we identify keys from the raw dump.
KNOWN_KEYS = {
    # CPU
    "TC0F": "CPU die (Apple SPMI)",
    "TC0P": "CPU proximity",
    "TC0C": "CPU core 0",
    "TC1C": "CPU core 1",
    "TC2C": "CPU core 2",
    "TC3C": "CPU core 3",
    "TCXC": "CPU Xeon core",
    "TCSA": "CPU SA",
    "TCGC": "CPU PECI GPU",
    "TCP0": "CPU package",
    # GPU - AMD R9 M370X candidates (we need to confirm which key is live)
    "TGDD": "GPU die (AMD)",
    "TG0D": "GPU die alt",
    "TG0P": "GPU proximity",
    "TGPD": "GPU proximity alt",
    # Memory / other
    "Tm0P": "memory bank 0",
    "Tm1P": "memory bank 1",
    "TM0P": "memory proximity",
    "TB0T": "battery",
    "Th0H": "heatsink A",
    "Th1H": "heatsink B",
    "TA0P": "ambient",
    "TW0P": "wireless",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_binary(command: str) -> list[str]:
    """Run macfan_smc with the given subcommand. Returns output lines."""
    binary = os.path.normpath(BINARY_PATH)

    if not os.path.isfile(binary):
        print(f"ERROR: binary not found at {binary}")
        print("       Build it first:  cd native && make")
        sys.exit(1)

    if not os.access(binary, os.X_OK):
        print(f"ERROR: binary is not executable: {binary}")
        print("       Run:  chmod +x native/macfan_smc")
        sys.exit(1)

    try:
        result = subprocess.run(
            [binary, command],
            capture_output=True,
            text=True,
            timeout=5
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: macfan_smc {command} timed out")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: could not run macfan_smc: {e}")
        sys.exit(1)

    if result.returncode != 0:
        print(f"ERROR: macfan_smc {command} exited with code {result.returncode}")
        if result.stderr:
            print(result.stderr.strip())
        sys.exit(1)

    return result.stdout.strip().splitlines()


def parse_temps(lines: list[str]) -> list[tuple[str, float]]:
    """
    Parse output of:  macfan_smc temps
    Format per line:  KEYNAME VALUE_CELSIUS
    Returns list of (key, celsius) tuples, sorted by key name.
    """
    temps = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                temps.append((parts[0], float(parts[1])))
            except ValueError:
                pass
    return sorted(temps, key=lambda x: x[0])


def parse_fans(lines: list[str]) -> list[dict]:
    """
    Parse output of:  macfan_smc fans
    Format:
        FAN 0
        ID Left Fan
        ACTUAL 2001
        MIN 1299
        MAX 6199
        SAFE 1299
        TARGET 2001
        MODE auto
    Returns list of dicts, one per fan.
    """
    fans = []
    current = None
    for line in lines:
        parts = line.strip().split(None, 1)  # split on first space only
        if not parts:
            continue
        tag = parts[0]
        val = parts[1] if len(parts) > 1 else ""

        if tag == "FAN":
            if current is not None:
                fans.append(current)
            current = {"index": int(val), "id": "?", "actual": -1,
                       "min": -1, "max": -1, "safe": -1,
                       "target": -1, "mode": "?"}
        elif current is not None:
            if tag == "ID":
                current["id"] = val.strip()
            elif tag == "ACTUAL":
                current["actual"] = int(float(val))
            elif tag == "MIN":
                current["min"] = int(float(val))
            elif tag == "MAX":
                current["max"] = int(float(val))
            elif tag == "SAFE":
                current["safe"] = int(float(val))
            elif tag == "TARGET":
                current["target"] = int(float(val))
            elif tag == "MODE":
                current["mode"] = val.strip()

    if current is not None:
        fans.append(current)

    return fans


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_temps(temps: list[tuple[str, float]]):
    print("=" * 50)
    print("  TEMPERATURES")
    print("=" * 50)
    if not temps:
        print("  No temperature data returned.")
        return

    for key, celsius in temps:
        label = KNOWN_KEYS.get(key, "")
        annotation = f"  ({label})" if label else ""
        print(f"  {key:<6}  {celsius:>6.2f} C{annotation}")

    print()

    # Highlight the GPU candidates so they're easy to spot
    gpu_candidates = [(k, v) for k, v in temps if k in ("TGDD", "TG0D", "TG0P", "TGPD")]
    if gpu_candidates:
        print("  >> GPU temperature candidates:")
        for key, celsius in gpu_candidates:
            label = KNOWN_KEYS.get(key, "")
            print(f"     {key}  {celsius:.2f} C  ({label})")
    else:
        print("  >> No known GPU keys found. Review the full list above.")
        print("     GPU keys on AMD R9 M370X are typically: TGDD, TG0D, TG0P")

    print()


def print_fans(fans: list[dict]):
    print("=" * 50)
    print("  FANS")
    print("=" * 50)
    if not fans:
        print("  No fan data returned.")
        return

    for fan in fans:
        print(f"  Fan {fan['index']}  ({fan['id']})")
        print(f"    Actual  : {fan['actual']:>5} RPM")
        print(f"    Min     : {fan['min']:>5} RPM")
        print(f"    Max     : {fan['max']:>5} RPM")
        print(f"    Safe    : {fan['safe']:>5} RPM")
        print(f"    Target  : {fan['target']:>5} RPM")
        print(f"    Mode    : {fan['mode']}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print("MacFanControl - Milestone 1 Probe")
    print("MacBookPro11,5 / macOS Monterey")
    print()

    # --- Temperatures ---
    temp_lines = run_binary("temps")
    temps = parse_temps(temp_lines)
    print_temps(temps)

    # --- Fans ---
    fan_lines = run_binary("fans")
    fans = parse_fans(fan_lines)
    print_fans(fans)

    print("Probe complete.")
    print()


if __name__ == "__main__":
    main()