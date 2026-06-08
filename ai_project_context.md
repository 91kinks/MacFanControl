# MacFanControl Project Status Report

## Project Goal

Create a lightweight replacement for Macs Fan Control specifically for a 2015 Intel MacBook Pro.

The user previously used Macs Fan Control successfully to regulate fan speed based on GPU temperature, but after installation the computer became extremely slow and nearly unusable. The exact cause was never isolated, but CPU/RAM usage is suspected.

The goal is NOT to replicate the full feature set of Macs Fan Control.

We only want approximately 5% of the functionality:

- Read GPU temperature
- Read fan RPM
- Set fan speed based on GPU temperature
- Support:
  - Auto mode
  - Fixed RPM mode
  - GPU-based fan curve mode
- Extremely lightweight daemon
- Eventually add menu bar icon

No graphs.
No historical logging.
No dashboards.
No dozens of sensors.
No unnecessary polling.

---

# Target Hardware

Machine:

MacBookPro11,5

Hardware:

- MacBook Pro Retina 15" (2015)
- Quad-Core Intel Core i7
- 2.8 GHz
- 16 GB RAM
- Dual Graphics:
  - Intel Iris Pro
  - AMD Radeon R9 M370X

Operating System:

macOS Monterey 12.7.6

SMC:

Version 2.30f2

---

# Project Architecture

MacFanControl/
├── native/
│   ├── smc.c               (from smcFanControl, unmodified except MACFAN_EMBEDDED guard)
│   ├── smc.h               (from smcFanControl, unmodified)
│   ├── macfan_smc.c        (our CLI helper, wraps smc.c)
│   └── Makefile
│
├── sensors.py
├── fan_curve.py
├── daemon.py
├── config.json
│
└── tests/
    └── probe.py

---

# Design Philosophy

Instead of talking directly to IOKit from Python:

Python
    ↓
subprocess
    ↓
macfan_smc helper
    ↓
SMC

This keeps:

- Python simple
- Hardware access isolated
- Easier debugging
- Easier testing
- Better crash recovery

The helper binary is responsible for all SMC access.

---

# Build Instructions

Requirements:
- Xcode Command Line Tools (xcode-select --install)
- IOKit and CoreFoundation frameworks (standard on all Macs)

Build:

cd native && make

This compiles smc.c and macfan_smc.c as a single translation unit.
smc.c has a MACFAN_EMBEDDED guard around its main() to prevent symbol clash.

Verify:

make check

---

# macfan_smc Binary - Confirmed Working Commands

./macfan_smc temps
    - Dumps all SMC temperature keys in SP78 format
    - Output: KEYNAME VALUE_CELSIUS (one per line)
    - Filters out zero/negative readings (unpopulated sensors)

./macfan_smc fans
    - Dumps all fan info
    - Output: structured key/value block per fan

sudo ./macfan_smc set-rpm <fan0_rpm> <fan1_rpm>
    - Sets fan 0 and fan 1 to independent target RPMs
    - Enables forced mode (FS! bitmask 0x0003)
    - Clamps each value to that fan's hardware min/max
    - fpe2 encoding: raw = rpm * 4, stored big-endian UInt16

sudo ./macfan_smc set-auto
    - Clears FS! bitmask (0x0000)
    - Returns both fans to Apple automatic control

---

# Confirmed SMC Keys - MacBookPro11,5

Temperature keys (SP78 format, value = raw_int16 / 256.0):

    TG0D    GPU die temperature (AMD R9 M370X) - PRIMARY SENSOR
    TG0P    GPU proximity
    TC1C    CPU core 1 (hottest core observed) - SECONDARY SENSOR
    TC0P    CPU proximity
    TB0T    Battery

Fan keys:

    FNum    Total fan count (= 2)
    F0Ac    Fan 0 actual RPM
    F0Mn    Fan 0 minimum RPM  = 2160
    F0Mx    Fan 0 maximum RPM  = 6156
    F0Tg    Fan 0 target RPM   (fpe2 encoded)
    F1Ac    Fan 1 actual RPM
    F1Mn    Fan 1 minimum RPM  = 2000
    F1Mx    Fan 1 maximum RPM  = 5700
    F1Tg    Fan 1 target RPM   (fpe2 encoded)
    FS!     Forced mode bitmask (bit 0 = fan 0, bit 1 = fan 1)

---

# Fan Configuration - Confirmed Working

Fan 0: Left side   — min 2160 RPM, max 6156 RPM
Fan 1: Right side  — min 2000 RPM, max 5700 RPM

Safe key returns -1 on this model (not populated).

---

# Fan Curve Configuration

Defined in config.json:

    start_temp:  66C    fan ramp begins
    max_temp:    95C    fan at maximum
    hysteresis:   4C    ramp-down begins at 62C (prevents oscillation)
    floor_rpm:  2600    both fans held here below start_temp
    emergency:  95C     override to hardware max immediately

Each fan scales independently against its own floor and max RPM.
Linear interpolation, rounded to nearest 50 RPM to prevent micro-adjustments.

Original successful Macs Fan Control curve that inspired this:
    Start ramp: 66C
    Maximum fan: ~95C
    Result: quiet, controlled, excellent thermal performance

---

# Python Layer

sensors.py:
    - Thin subprocess wrapper around macfan_smc binary
    - read_gpu_temp(binary, key) -> float | None
    - read_cpu_temp(binary, key) -> float | None
    - read_fans(binary) -> list[dict] | None
    - set_rpm(binary, rpm0, rpm1) -> bool
    - set_auto(binary) -> bool

fan_curve.py:
    - calc_rpm(temp, floor_rpm, max_rpm, start_temp, max_temp, hysteresis, ramping_up) -> int
    - Pure calculation, no I/O, easily testable

daemon.py:
    - Loads config.json
    - Runs poll loop every N seconds (default 3s)
    - Calls sensors.py, fan_curve.py, applies RPM via macfan_smc
    - Handles SIGINT/SIGTERM -> restores auto control on exit
    - Emergency override if GPU >= 95C
    - Sensor failure -> restore auto and exit
    - Skips writes if RPM unchanged from last tick
    - Supports --dry-run flag (reads only, no writes)
    - Supports --config flag for custom config path

Usage:
    sudo python3 daemon.py
    sudo python3 daemon.py --dry-run
    sudo python3 daemon.py --config /path/to/config.json

---

# Milestones

## Milestone 1 - COMPLETE
Read sensors (GPU temp, CPU temp, fan RPM).
Confirmed working via tests/probe.py.

## Milestone 2 - COMPLETE
Read fan limits (min/max RPM per fan).
Confirmed: Fan0 2160-6156, Fan1 2000-5700.

## Milestone 3 - COMPLETE
Write fixed fan RPM.
Confirmed: forced mode engages, fans hit target, auto restore works.

## Milestone 4 - COMPLETE
Fan curve daemon.
Confirmed: GPU-based curve running, hysteresis working, signal handling clean.

## Milestone 5 - COMPLETE
Auto-start and menu bar application.

Next steps:
1. Publish to Github and make public
2. Create a Video showing its usability

---

# Development Environment

- Code written on Windows in VSCode
- Pulled to MacBook via Git
- Compiled and run on MacBook
- .gitattributes enforces LF line endings for all source files
- .vscode/c_cpp_properties.json suppresses Windows IntelliSense errors
  for macOS-only headers (IOKit, unistd.h etc) - cosmetic only

---

# Source Reference

SMC implementation sourced from smcFanControl by hholtmann:
https://github.com/hholtmann/smcFanControl

smc.c and smc.h are used with minor modification (MACFAN_EMBEDDED guard).
Original license: GNU GPL v2.

Our project should carry the same GPL v2 license on release.
