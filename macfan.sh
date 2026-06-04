#!/bin/bash
# macfan.sh
# MacFanControl - Process management shortcuts
#
# Usage:
#   ./macfan.sh status              - show status of daemon and menu bar
#   ./macfan.sh start               - start both daemon and menu bar
#   ./macfan.sh stop                - stop both daemon and menu bar
#   ./macfan.sh restart             - restart both
#   ./macfan.sh start daemon        - start daemon only
#   ./macfan.sh start menubar       - start menu bar only
#   ./macfan.sh stop daemon         - stop daemon only
#   ./macfan.sh stop menubar        - stop menu bar only
#   ./macfan.sh restart daemon      - restart daemon only
#   ./macfan.sh restart menubar     - restart menu bar only
#
# Tip: add an alias to your ~/.zshrc for quick access:
#   alias macfan='/Users/koryinks/MacFanControl/macfan.sh'
# Then you can just run:
#   macfan status
#   macfan start
#   macfan stop menubar

DAEMON_PLIST="$HOME/Library/LaunchAgents/com.macfancontrol.daemon.plist"
MENUBAR_PLIST="$HOME/Library/LaunchAgents/com.macfancontrol.menubar.plist"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

is_running() {
    launchctl list | grep -q "$1"
}

plist_installed() {
    test -f "$1"
}

print_status() {
    local label=$1
    local plist=$2

    if ! plist_installed "$plist"; then
        echo -e "  ${YELLOW}$label${NC}  not installed (run ./install.sh first)"
        return
    fi

    if is_running "$label"; then
        local pid
        pid=$(launchctl list | grep "$label" | awk '{print $1}')
        echo -e "  ${GREEN}●${NC} $label  running (PID $pid)"
    else
        echo -e "  ${RED}○${NC} $label  stopped"
    fi
}

start_agent() {
    local label=$1
    local plist=$2

    if ! plist_installed "$plist"; then
        echo "  Error: $plist not found. Run ./install.sh first."
        return 1
    fi

    if is_running "$label"; then
        echo "  $label is already running"
    else
        launchctl load "$plist" && echo -e "  ${GREEN}✓${NC} $label started" || echo "  Error starting $label"
    fi
}

stop_agent() {
    local label=$1
    local plist=$2

    if ! plist_installed "$plist"; then
        echo "  Error: $plist not found."
        return 1
    fi

    if is_running "$label"; then
        launchctl unload "$plist" && echo -e "  ${GREEN}✓${NC} $label stopped" || echo "  Error stopping $label"
    else
        echo "  $label is already stopped"
    fi
}

restart_agent() {
    stop_agent "$1" "$2"
    sleep 0.5
    start_agent "$1" "$2"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

CMD=${1:-status}
TARGET=${2:-both}

echo ""

case "$CMD" in
    status)
        echo "MacFanControl status:"
        echo ""
        print_status "com.macfancontrol.daemon"  "$DAEMON_PLIST"
        print_status "com.macfancontrol.menubar" "$MENUBAR_PLIST"
        ;;

    start)
        echo "Starting MacFanControl..."
        case "$TARGET" in
            daemon)  start_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST" ;;
            menubar) start_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST" ;;
            both)
                start_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST"
                start_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST"
                ;;
            *) echo "  Unknown target: $TARGET. Use daemon, menubar, or omit for both." ;;
        esac
        ;;

    stop)
        echo "Stopping MacFanControl..."
        case "$TARGET" in
            daemon)  stop_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST" ;;
            menubar) stop_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST" ;;
            both)
                stop_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST"
                stop_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST"
                ;;
            *) echo "  Unknown target: $TARGET. Use daemon, menubar, or omit for both." ;;
        esac
        ;;

    restart)
        echo "Restarting MacFanControl..."
        case "$TARGET" in
            daemon)  restart_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST" ;;
            menubar) restart_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST" ;;
            both)
                restart_agent "com.macfancontrol.daemon"  "$DAEMON_PLIST"
                restart_agent "com.macfancontrol.menubar" "$MENUBAR_PLIST"
                ;;
            *) echo "  Unknown target: $TARGET. Use daemon, menubar, or omit for both." ;;
        esac
        ;;

    *)
        echo "Usage: ./macfan.sh [status|start|stop|restart] [daemon|menubar]"
        echo ""
        echo "  ./macfan.sh status"
        echo "  ./macfan.sh start"
        echo "  ./macfan.sh stop"
        echo "  ./macfan.sh restart"
        echo "  ./macfan.sh start menubar"
        echo "  ./macfan.sh stop daemon"
        ;;
esac

echo ""