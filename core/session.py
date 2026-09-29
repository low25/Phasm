"""
GameSession
===========
Monitors a running emulator process and emits session_ended when it exits.

When the emulator process exits (either the game ended inside it or the user
closed the emulator window), the session is marked done.  If the *game* exits
first inside an emulator that keeps running (e.g. RPCS3 back to its menu),
we detect that by monitoring the emulator's stdout/stderr for known "game
stopped" strings and then send SIGTERM to the emulator so the user doesn't
have to close it manually.

Emulator exit patterns (regex searched in log lines):
  PCSX2 / ShadPS4: process itself quits → wait() returns naturally
  RPCS3:           prints lines containing "Game ended", "Stopping", etc.
  Ryujinx:         exits naturally when game window closes
"""

from PySide6.QtCore import QThread, Signal
import subprocess
import threading
import time
import re
import os
import signal


# Lines from emulator stdout/stderr that mean "game has stopped, kill emu"
_GAME_STOP_PATTERNS = [
    re.compile(r"game ended", re.IGNORECASE),
    re.compile(r"stopping\.\.\.", re.IGNORECASE),
    re.compile(r"Emu\.Stop", re.IGNORECASE),
    re.compile(r"Game process exited", re.IGNORECASE),
    re.compile(r"CELL_EAGAIN.*stop", re.IGNORECASE),
]


def _kill_process(proc: subprocess.Popen):
    """Gracefully terminate a process, escalating to SIGKILL if needed."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return   # already dead
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass


class GameSession(QThread):
    session_ended = Signal(str, float)  # game_key, duration_seconds

    def __init__(self, game_key, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self.game_key = game_key
        self.process = process
        self.start_time = time.monotonic()
        self._stop_event = threading.Event()

    def run(self):
        # Start a background thread that tails stdout+stderr for stop signals
        log_thread = threading.Thread(target=self._watch_logs, daemon=True)
        log_thread.start()

        # Wait for the emulator process to exit (covers all cases)
        self.process.wait()

        duration = time.monotonic() - self.start_time
        self._stop_event.set()

        self.session_ended.emit(self.game_key, duration)

    def _watch_logs(self):
        """Read the emulator's stdout/stderr and kill it when the game stops."""
        streams = []
        try:
            if self.process.stdout:
                streams.append(self.process.stdout)
            if self.process.stderr:
                streams.append(self.process.stderr)
        except Exception:
            return

        if not streams:
            return

        import select as _select

        while not self._stop_event.is_set():
            try:
                ready, _, _ = _select.select(streams, [], [], 0.2)
            except Exception:
                break
            for s in ready:
                try:
                    line = s.readline()
                    if not line:
                        continue
                    text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                    for pat in _GAME_STOP_PATTERNS:
                        if pat.search(text):
                            print(f"[SESSION] Detected game stop in emulator log → killing emulator")
                            _kill_process(self.process)
                            return
                except Exception:
                    pass

    def kill(self):
        self._stop_event.set()
        _kill_process(self.process)
