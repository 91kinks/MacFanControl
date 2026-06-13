import threading
import subprocess

# ---------------------------------------------------------------------------
# Speed limit watcher — background thread
# ---------------------------------------------------------------------------

class SpeedLimitWatcher:
    """
    Runs `pmset -g thermlog` in a background thread and updates self.current
    the instant a new CPU_Speed_Limit line arrives. The daemon tick() reads
    self.current directly — zero subprocess overhead per poll cycle.

    self.current is None until the first reading arrives (pmset only prints
    on state changes, so if the machine is idle it may take a moment).
    Once populated it always holds the most recent known value.

    The thread is daemonized so it dies automatically when the main process
    exits, including on SIGKILL. The pmset process is tracked and terminated
    on stop() so it doesn't linger as an orphan.
    """

    def __init__(self):
        self.current: int | None = None
        self._lock   = threading.Lock()
        self._proc   = None
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self):
        try:
            self._proc = subprocess.Popen(
                ["pmset", "-g", "thermlog"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )
            for line in self._proc.stdout:
                if "CPU_Speed_Limit" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        try:
                            value = int(parts[1].strip())
                            with self._lock:
                                self.current = value
                        except ValueError:
                            pass
        except Exception:
            pass  # thread dies silently; self.current retains last known value

    def get(self) -> int | None:
        """Thread-safe read of the current speed limit."""
        with self._lock:
            return self.current

    def stop(self):
        """Terminate the pmset process on daemon shutdown."""
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass