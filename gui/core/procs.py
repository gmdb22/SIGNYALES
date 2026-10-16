"""
Signyales GUI — run a command in the background and stream its output.

Used by every "test" button. No Tk imports: callbacks are plain functions,
and the window code moves them onto the Tk thread itself.
"""

import signal
import subprocess
import threading
import time

from .env import IS_WINDOWS, child_env


class ProcessRunner:
    """
    Runs one command. on_line(text) is called for every output line (stdout
    and stderr merged); on_exit(returncode, timed_out) once at the end.
    """

    def __init__(self, on_line, on_exit):
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc = None
        self._timed_out = False
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, cmd, cwd, timeout=None):
        self._timed_out = False
        self._stopping = False
        kwargs = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self._proc = subprocess.Popen(
                [str(c) for c in cmd], cwd=str(cwd), env=child_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
        except FileNotFoundError as exc:
            self._on_line(f"Could not start: {exc}")
            self._on_exit(None, False)
            return
        threading.Thread(target=self._pump, daemon=True).start()
        if timeout:
            threading.Thread(target=self._watchdog, args=(timeout,), daemon=True).start()

    def _pump(self):
        for line in self._proc.stdout:
            self._on_line(line.rstrip("\n"))
        rc = self._proc.wait()
        self._on_exit(rc, self._timed_out)

    def _watchdog(self, timeout):
        deadline = time.monotonic() + timeout
        while self.running and time.monotonic() < deadline:
            time.sleep(0.2)
        if self.running:
            self._timed_out = True
            self.stop()

    def stop(self):
        """Asks the process to stop like Ctrl+C would, then kills it after 3 s."""
        if not self.running or self._stopping:
            return
        self._stopping = True
        try:
            self._proc.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)
        except (OSError, ValueError):
            pass

        def _kill_later(p=self._proc):
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        threading.Thread(target=_kill_later, daemon=True).start()
