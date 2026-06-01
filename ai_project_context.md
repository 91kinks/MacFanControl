# MacFanLite Project Status Report

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

Current planned architecture:

MacFanLite/

├── native/
│   └── macfan_smc
│
├── sensors.py
├── smc.py
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

The helper binary will be responsible for all SMC access.

---

# Original Fan Curve Used Successfully

User's previous Macs Fan Control configuration:

Control Sensor:
- GPU Temperature

Curve:

Start ramp:
- 66°C

Maximum fan:
- Approximately 95°C

Result:

- Mac remained quiet
- Temperatures stayed under control
- Fan behavior was excellent

This configuration should be the baseline target.

---

# Planned Safety Features

If GPU > 95°C:

- Override everything
- Set maximum fan speed

If sensor read fails:

- Restore Apple automatic control

If daemon crashes:

- Restore Apple automatic control

Add hysteresis:

Example:

Fan turns on:
- 66°C

Fan turns off:
- 62°C

Prevents rapid fan oscillation.

---

# Milestones

## Milestone 1

Read sensors.

Need:

- GPU temperature
- CPU temperature
- Fan RPM

Goal:

python tests/probe.py

Output:

GPU: 68.4°C
CPU: 57.2°C
Left Fan: 2001 RPM
Right Fan: 1998 RPM

No fan control yet.

---

## Milestone 2

Read fan limits.

Need:

- Current RPM
- Minimum RPM
- Maximum RPM

---

## Milestone 3

Write fixed fan RPM.

Example:

macfan_smc set-rpm 3500

Verify fan actually changes speed.

---

## Milestone 4

Implement fan curve.

Example config:

{
    "mode": "gpu_curve",
    "start_temp": 66,
    "max_temp": 95,
    "min_rpm": 2000,
    "max_rpm": 6200
}

Daemon:

while True:
    gpu = get_gpu_temp()
    rpm = curve(gpu)
    set_rpm(rpm)
    sleep(3)

---

## Milestone 5

Menu bar application.

Display:

- GPU Temp
- Current Fan RPM
- Active Mode

Nothing else.

---

# Research Findings

Initially attempted:

brew install smckit

Result:

No available formula.

SMCKit no longer available through default Homebrew repositories.

---

Homebrew Searches

brew search smc

Returned:

- smcfancontrol
- smcfancontrol@beta

---

brew info smcfancontrol

Returned:

smcFanControl 2.6

GitHub:

https://github.com/hholtmann/smcFanControl

Open source.

---

# Critical Discovery

Located source files:

smc-command/smc.c
smc-command/smc.h

Repository:

https://github.com/hholtmann/smcFanControl

Direct links:

https://github.com/hholtmann/smcFanControl/blob/master/smc-command/smc.c

https://github.com/hholtmann/smcFanControl/blob/master/smc-command/smc.h

These files appear to contain the SMC implementation used by smcFanControl.

This likely eliminates the need to reverse engineer SMC communication.

The next development step should be:

1. Examine smc.c
2. Determine:
   - Read temperature functions
   - Read fan functions
   - Write fan functions
3. Build a minimal CLI helper:

Examples:

./macfan_smc gpu-temp

./macfan_smc fan-rpm

./macfan_smc set-rpm 3500

Then wrap these commands in Python.

---

# Current Development Decision

Do NOT start with fan control.

First objective:

Build a probe utility.

Only read:

- GPU temp
- CPU temp
- Fan RPM

Confirm reliable operation on Monterey 12.7.6.

Only after successful sensor reads should fan writing functionality be added.

---

# Long-Term Goal

Replace Macs Fan Control with a lightweight open-source implementation specifically optimized for:

- MacBookPro11,5
- GPU-based fan control
- Low CPU usage
- Low memory usage
- Simple maintenance

The intent is to preserve hardware lifespan and thermal performance without the overhead experienced from Macs Fan Control.