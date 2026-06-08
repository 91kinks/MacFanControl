# MacFanControl

A lightweight fan control daemon for 2015 Intel MacBook Pro (MacBookPro11,5). 
**Note: Should be able to be tailored to other Macbooks as well**

Built as a minimal replacement for Macs Fan Control, which caused severe system slowdowns on this hardware. This project uses less than 1% of CPU and a few MB of RAM.

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
- Menu bar display showing GPU temp and fan RPM
- Dry-run mode for testing without touching the fans
- Single install script handles all setup automatically
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
├── menubar.py              # Menu bar status display (read-only)
├── config.json             # User configuration
├── macfan.sh               # Process management shortcuts
├── install.sh              # Automated install script
│
├── com.macfancontrol.daemon.plist    # launchd template (daemon)
├── com.macfancontrol.menubar.plist   # launchd template (menu bar)
│
└── tests/
    └── probe.py            # Read all sensors and fan info (no writes)
```

---

## Requirements

- macOS (tested on Monterey 12.7.6)
- Xcode Command Line Tools
- Python 3

Install Xcode Command Line Tools if needed:
```bash
xcode-select --install
```

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/91kinks/MacFanControl.git
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

This dumps all temperature keys and fan info from your SMC with no writes. Look for your GPU key in the output — on the MacBookPro11,5 it is `TG0D`. If your machine reports a different key, update `config.json` before proceeding.

### 4. Review and edit config.json

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

Update `gpu_temp_key` if your probe output showed a different key. Adjust `floor_rpm`, `start_temp`, and `max_temp` to taste.

### 5. Set up the Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install rumps
```

### 6. Test with dry-run

```bash
sudo python3 daemon.py --dry-run
```

This runs the full loop — reading sensors and computing targets — without writing anything to the SMC. Verify the output looks sensible, then Ctrl+C to exit.

### 7. Run the daemon

```
sudo python3 daemon.py
```
Runs the daemon with the config file inputs reading and writing to the SMC.
Ctrl+C will cleanly restore auto fan control before exiting.

### 8. Run the install script

```bash
chmod +x install.sh
./install.sh
```

The install script will:
- Verify all requirements are met
- Create the logs directory
- Write both launchd plists with correct paths for your system
- Add a passwordless sudo rule for the macfan_smc binary only
- Load both launch agents (daemon + menu bar)

After install, both the daemon and menu bar app start automatically on every login.

---

## Security

MacFanControl requires passwordless sudo access for the `macfan_smc` binary in order to write to the SMC without prompting on every fan update.

The sudoers rule is scoped as narrowly as possible — it grants passwordless sudo for that one specific binary path only, nothing else.

To prevent privilege escalation via binary replacement, `install.sh` automatically locks the binary to root ownership after install:

```
-rwxr-xr-x  root  wheel  native/macfan_smc
```

This means even if an attacker gains user-level access to your machine, they cannot replace the binary with a malicious one without already having root — which breaks the escalation chain.

If you ever rebuild the binary (`make`), re-run `./install.sh` to reapply the ownership lock.

---

## Uninstall

```bash
./install.sh --uninstall
```

This unloads both launch agents, removes the plists, removes the sudoers rule, and restores Apple auto fan control.

---

## Managing Processes

After install, use the `macfan` alias (added automatically by `install.sh`) to control both processes:

```bash
macfan status               # show whether daemon and menu bar are running
macfan start                # start both
macfan stop                 # stop both
macfan restart              # restart both
macfan start menubar        # start menu bar only
macfan stop menubar         # stop menu bar only
macfan restart daemon       # restart daemon only
```

If the alias isn't active yet in your current terminal:
```bash
source ~/.zshrc
```

To start/stop manually without the alias:
```bash
launchctl load   ~/Library/LaunchAgents/com.macfancontrol.menubar.plist
launchctl unload ~/Library/LaunchAgents/com.macfancontrol.menubar.plist
```

---

## Manual Fan Control

The `macfan_smc` binary can be used directly without the daemon:

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

- **Below 66°C** — fans hold at floor RPM (quiet)
- **66°C to 95°C** — linear ramp to max RPM
- **At 95°C** — immediate override to hardware maximum
- **Hysteresis** — fans only start ramping down once temp drops below 62°C, preventing rapid oscillation

Each fan scales against its own hardware min/max independently.

---

## Logs

```
logs/daemon.log     # daemon stdout (temps, RPM decisions)
logs/daemon.err     # daemon stderr (errors)
logs/menubar.log    # menu bar stdout
logs/menubar.err    # menu bar stderr
```

---

## SMC Keys (MacBookPro11,5)

| Key  | Description           | Notes                         |
|------|-----------------------|-------------------------------|
| TG0D | GPU die temperature   | Primary control sensor        |
| TC1C | CPU core 1 temperature| Secondary / informational     |
| F0Tg | Fan 0 target RPM      | fpe2 encoded, big-endian      |
| F1Tg | Fan 1 target RPM      | fpe2 encoded, big-endian      |
| FS!  | Forced mode bitmask   | bit 0 = fan 0, bit 1 = fan 1  |

---

## Acknowledgements

SMC communication is based on [smcFanControl](https://github.com/hholtmann/smcFanControl) by hholtmann. The `smc.c` and `smc.h` files are used under the GNU GPL v2 license.

---

## License

GNU General Public License v2.0

This project uses code from smcFanControl (GPL v2), so the same license applies here. See [GPL v2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html).