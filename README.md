# MacFanControl

A lightweight fan control daemon for 2015 Intel MacBook Pro (MacBookPro11,5).

Built as a minimal replacement for Macs Fan Control, which caused severe system slowdowns on this hardware. This project uses less than 1% of the CPU and a few MB of RAM.

---

## Why This Exists

Macs Fan Control is a great app, but on older MacBook Pros it can cause the system to become nearly unusable due to CPU and RAM overhead. This project does exactly one thing well: read the GPU temperature and adjust fan speed accordingly, with almost zero system impact.

Apple's built-in auto fan control on the 2015 MacBook Pro is overly aggressive — fans ramp up fast and stay high long after temperatures drop. This daemon uses a smoother, more conservative curve that keeps the machine quiet while still protecting the hardware.

---

## Target Hardware

- **Machine:** MacBookPro11,5 (MacBook Pro Retina 15-inch, Mid 2015)
- **CPU:** Quad-Core Intel Core i7 2.8 GHz
- **GPU:** AMD Radeon R9 M370X + Intel Iris Pro
- **OS:** macOS Monterey 12.7.6
- **SMC:** Version 2.30f2

May work on other 2013–2015 Intel MacBook Pros with similar SMC key layouts. The probe tool will tell you what keys your machine exposes.

---

## Features

- GPU temperature-based fan curve
- Independent RPM control for left and right fans
- Configurable curve, floor RPM, and hysteresis
- Emergency override at configurable temperature ceiling
- Automatic restore to Apple control on crash or exit
- Runs as a login daemon via launchd
- Dry-run mode for testing without touching the fans
- Extremely low resource usage

---

## Project Structure

```
MacFanControl/
├── native/
│   ├── smc.c               # SMC implementation (from smcFanControl, GPL v2)
│   ├── smc.h
│   ├── macfan_smc.c        # Lightweight CLI helper wrapping smc.c
│   └── Makefile
│
├── sensors.py              # Subprocess wrapper around macfan_smc
├── fan_curve.py            # Fan curve calculation (pure, no I/O)
├── daemon.py               # Main daemon loop
├── config.json             # User configuration
│
├── com.macfancontrol.daemon.plist   # launchd login agent
│
└── tests/
    └── probe.py            # Read all sensors and fan info (no writes)
```

---

## Requirements

- macOS (tested on Monterey 12.7.6)
- Xcode Command Line Tools
- Python 3 (`/usr/local/bin/python3`)

Install Xcode Command Line Tools if needed:
```bash
xcode-select --install
```

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/MacFanControl.git
cd MacFanControl
```

### 2. Build the SMC helper binary

```bash
cd native
make check    # verify your build environment
make
cd ..
```

### 3. Run the probe to verify your sensors

```bash
python3 tests/probe.py
```

This will dump all temperature keys and fan info from your SMC with no writes. Look for your GPU key in the output — on the MacBookPro11,5 it is `TG0D`.

### 4. Edit config.json

```json
{
    "binary": "native/macfan_smc",
    "sensor": {
        "gpu_temp_key": "TG0D",
        "cpu_temp_key": "TC1C"
    },
    "poll_interval_seconds": 3,
    "fan0": {
        "label": "Left side",
        "floor_rpm": 2600,
        "max_rpm": 6156
    },
    "fan1": {
        "label": "Right side",
        "floor_rpm": 2600,
        "max_rpm": 5700
    },
    "curve": {
        "start_temp": 66,
        "max_temp": 95,
        "hysteresis": 4
    },
    "safety": {
        "emergency_temp": 95,
        "sensor_fail_action": "auto"
    }
}
```

Adjust `floor_rpm`, `start_temp`, and `max_temp` to your preference. Use the probe output to confirm your GPU key before running the daemon.

### 5. Test with dry-run

```bash
sudo python3 daemon.py --dry-run
```

This runs the full loop — reading sensors and computing targets — without writing anything to the SMC. Verify the output looks sensible, then Ctrl+C to exit.

### 6. Run the daemon

```bash
sudo python3 daemon.py
```

Ctrl+C will cleanly restore auto fan control before exiting.

---

## Auto-start on Login (launchd)

### 1. Create the logs directory

```bash
mkdir -p /Users/YOUR_USERNAME/MacFanControl/logs
```

### 2. Allow passwordless sudo for the binary

```bash
echo "YOUR_USERNAME ALL=(ALL) NOPASSWD: /Users/YOUR_USERNAME/MacFanControl/native/macfan_smc" | sudo tee /etc/sudoers.d/macfancontrol
```

### 3. Edit the plist

Open `com.macfancontrol.daemon.plist` and replace every occurrence of `/Users/koryinks/` with your own home directory path.

### 4. Install the plist

```bash
cp com.macfancontrol.daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.macfancontrol.daemon.plist
```

### 5. Verify it is running

```bash
launchctl list | grep macfancontrol
cat ~/MacFanControl/logs/daemon.log
```

### Stop / unload

```bash
launchctl unload ~/Library/LaunchAgents/com.macfancontrol.daemon.plist
```

---

## Manual Fan Control

The `macfan_smc` binary can be used directly:

```bash
# Read all temperature sensors
./native/macfan_smc temps

# Read fan info (RPM, min, max, mode)
./native/macfan_smc fans

# Set fan 0 and fan 1 to independent RPM targets
sudo ./native/macfan_smc set-rpm 3000 2800

# Return both fans to Apple auto control
sudo ./native/macfan_smc set-auto
```

---

## How the Fan Curve Works

The curve is a linear ramp between two temperature points:

```
RPM
 ^
max ─────────────────────────────/──────
     |                          /
     |                         /
floor───────────────────────/──
     |              ───────/
     |         ────/
     +─────────────────────────────> GPU Temp (C)
              62  66              95
               ↑   ↑               ↑
          ramp-down  ramp-up     emergency
          threshold  threshold    override
```

- Below 66°C — fans hold at floor RPM (quiet)
- 66°C to 95°C — linear ramp to max RPM
- At 95°C — immediate override to hardware maximum
- Hysteresis — fans only start ramping down once temp drops below 62°C, preventing rapid oscillation

Each fan scales against its own hardware min/max independently.

---

## SMC Keys (MacBookPro11,5)

| Key   | Description              | Notes                        |
|-------|--------------------------|------------------------------|
| TG0D  | GPU die temperature      | Primary control sensor       |
| TC1C  | CPU core 1 temperature   | Secondary / informational    |
| F0Tg  | Fan 0 target RPM         | fpe2 encoded, big-endian     |
| F1Tg  | Fan 1 target RPM         | fpe2 encoded, big-endian     |
| FS!   | Forced mode bitmask      | bit 0 = fan 0, bit 1 = fan 1 |

---

## Acknowledgements

SMC communication is based on [smcFanControl](https://github.com/hholtmann/smcFanControl) by hholtmann. The `smc.c` and `smc.h` files are used under the GNU GPL v2 license.

---

## License

GNU General Public License v2.0 — see [GPL v2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html).

This project uses code from smcFanControl (GPL v2), so the same license applies here.
