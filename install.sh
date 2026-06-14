#!/bin/bash
# install.sh
# MacFanControl - Automated install script
#
# Detects install location, Python path, and username automatically.
# Writes launchd plists, sudoers rule, and log directory.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# To uninstall:
#   ./install.sh --uninstall

set -e

# ---------------------------------------------------------------------------
# Colors for output
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # no color

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; }

# ---------------------------------------------------------------------------
# Detect environment
# ---------------------------------------------------------------------------

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
USERNAME="$(whoami)"
VENV_PYTHON="$INSTALL_DIR/venv/bin/python3"
BINARY="$INSTALL_DIR/native/macfan_smc"
DAEMON_PLIST="$HOME/Library/LaunchAgents/com.macfancontrol.daemon.plist"
MENUBAR_PLIST="$HOME/Library/LaunchAgents/com.macfancontrol.menubar.plist"
SUDOERS_FILE="/etc/sudoers.d/macfancontrol"
LOG_DIR="$INSTALL_DIR/logs"

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

if [ "$1" == "--uninstall" ]; then
    echo ""
    echo "MacFanControl - Uninstalling..."
    echo ""

    # Unload launch agents
    if launchctl list | grep -q "com.macfancontrol.daemon"; then
        launchctl unload "$DAEMON_PLIST" 2>/dev/null && ok "Daemon unloaded" || warn "Daemon was not loaded"
    fi
    if launchctl list | grep -q "com.macfancontrol.menubar"; then
        launchctl unload "$MENUBAR_PLIST" 2>/dev/null && ok "Menu bar unloaded" || warn "Menu bar was not loaded"
    fi

    # Remove plists
    rm -f "$DAEMON_PLIST"  && ok "Removed daemon plist"
    rm -f "$MENUBAR_PLIST" && ok "Removed menubar plist"

    # Remove sudoers rule
    sudo rm -f "$SUDOERS_FILE" && ok "Removed sudoers rule"

    # Remove alias from .zshrc
    if grep -q "MacFanControl alias" "$HOME/.zshrc" 2>/dev/null; then
        grep -v "MacFanControl alias" "$HOME/.zshrc" | grep -v "alias macfan=" > /tmp/.zshrc_tmp

        mv /tmp/.zshrc_tmp "$HOME/.zshrc"
        ok "Removed shell alias from ~/.zshrc"
    fi

    # Restore binary ownership to user
    if [ -f "$BINARY" ]; then
        sudo chown "$USERNAME":staff "$BINARY"
        ok "Binary ownership restored to $USERNAME"
    fi

    # Restore auto fan control just in case
    if [ -f "$BINARY" ]; then
        sudo "$BINARY" set-auto 2>/dev/null && ok "Fans restored to auto control"
    fi

    echo ""
    echo "Uninstall complete."
    echo ""
    exit 0
fi

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

echo ""
echo "MacFanControl - Install"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Install dir : $INSTALL_DIR"
echo "  Username    : $USERNAME"
echo "  Python      : $VENV_PYTHON"
echo "  Binary      : $BINARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

echo "Checking requirements..."

# venv Python
if [ ! -f "$VENV_PYTHON" ]; then
    err "venv not found at $VENV_PYTHON"
    echo "    Run:  python3 -m venv venv && source venv/bin/activate && pip install rumps"
    exit 1
fi
ok "venv Python found"

# rumps
if ! "$VENV_PYTHON" -c "import rumps" 2>/dev/null; then
    err "rumps not installed in venv"
    echo "    Run:  source venv/bin/activate && pip install rumps"
    exit 1
fi
ok "rumps installed"

# Binary
if [ ! -f "$BINARY" ]; then
    err "macfan_smc binary not found"
    echo "    Run:  cd native && make"
    exit 1
fi
ok "macfan_smc binary found"

echo ""

# ---------------------------------------------------------------------------
# Create logs directory
# ---------------------------------------------------------------------------

mkdir -p "$LOG_DIR"
ok "Logs directory: $LOG_DIR"

# ---------------------------------------------------------------------------
# Write daemon plist
# ---------------------------------------------------------------------------

cat > /tmp/com.macfancontrol.daemon.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.macfancontrol.daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$INSTALL_DIR/daemon.py</string>
        <string>--config</string>
        <string>$INSTALL_DIR/config.json</string>
    </array>

    <key>RunAtLoad</key>
    <false/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/daemon.err</string>

    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

cp /tmp/com.macfancontrol.daemon.plist "$DAEMON_PLIST"
ok "Daemon plist written to $DAEMON_PLIST"

# ---------------------------------------------------------------------------
# Write menubar plist
# ---------------------------------------------------------------------------

cat > /tmp/com.macfancontrol.menubar.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.macfancontrol.menubar</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$INSTALL_DIR/menubar.py</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/menubar.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/menubar.err</string>

    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

cp /tmp/com.macfancontrol.menubar.plist "$MENUBAR_PLIST"
ok "Menubar plist written to $MENUBAR_PLIST"

# ---------------------------------------------------------------------------
# Write sudoers rule
# ---------------------------------------------------------------------------

echo "$USERNAME ALL=(ALL) NOPASSWD: $BINARY" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"
ok "Sudoers rule written for $USERNAME"

# ---------------------------------------------------------------------------
# Load launch agents
# ---------------------------------------------------------------------------

echo ""
echo "Loading launch agents..."

# Unload first if already running (clean reinstall)
launchctl unload "$DAEMON_PLIST"  2>/dev/null || true
launchctl unload "$MENUBAR_PLIST" 2>/dev/null || true

launchctl load "$DAEMON_PLIST"  && ok "Daemon started" || err "Failed to start daemon"
launchctl load "$MENUBAR_PLIST" && ok "Menu bar started" || err "Failed to start menu bar"
# ---------------------------------------------------------------------------
# Lock binary ownership to root
# Prevents unprivileged users from replacing the binary
# with a malicious one that would run as root via sudoers
# ---------------------------------------------------------------------------

sudo chown root:wheel "$BINARY"
sudo chmod 755 "$BINARY"
ok "Binary ownership locked to root:wheel"

# ---------------------------------------------------------------------------
# Lock script permissions (read/execute only, no writes)
# ---------------------------------------------------------------------------

chmod 555 "$INSTALL_DIR/install.sh"
chmod 555 "$INSTALL_DIR/macfan.sh"
ok "Script permissions set to 555 (read/execute only)"

# ---------------------------------------------------------------------------
# Make macfan.sh executable
# ---------------------------------------------------------------------------

chmod +x "$INSTALL_DIR/macfan.sh"
ok "macfan.sh is executable"

# ---------------------------------------------------------------------------
# Add shell alias
# ---------------------------------------------------------------------------

ZSHRC="$HOME/.zshrc"
ALIAS_LINE="alias macfan='$INSTALL_DIR/macfan.sh'"
ALIAS_MARKER="# MacFanControl alias"

if grep -q "MacFanControl alias" "$ZSHRC" 2>/dev/null; then
    warn "Shell alias already exists in $ZSHRC (skipping)"
else
    echo "" >> "$ZSHRC"
    echo "$ALIAS_MARKER" >> "$ZSHRC"
    echo "$ALIAS_LINE"   >> "$ZSHRC"
    ok "Shell alias added to $ZSHRC"
    echo "    Run: source ~/.zshrc  (or open a new terminal)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  Install complete.${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Verify:   launchctl list | grep macfancontrol"
echo "  Logs:     $LOG_DIR/"
echo "  Control:   macfan status / start / stop / restart"
echo "  Uninstall: ./install.sh --uninstall"
echo ""