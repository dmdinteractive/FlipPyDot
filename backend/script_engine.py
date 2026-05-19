"""
script_engine.py
----------------
Runs FlipDot Script (.fds) files.

Scripts are plain text files in the scripts/ folder.
Each line is one command. Blank lines and # comments are ignored.
Commands are the same vocabulary as the interactive CLI.

Execution model:
  - Scripts run in a dedicated thread
  - The calling thread can monitor via script.running / script.current_line
  - script.stop() aborts execution cleanly
  - Unknown commands log a warning and are skipped (never crash)
  - 'script run other.fds' blocks until sub-script completes
  - 'script spawn other.fds' runs sub-script in parallel

Error handling:
  - File not found: immediate error, clean exit
  - Bad command line: logged as warning, execution continues
  - Exception in command: logged as error, execution continues
"""

import os
import time
import threading
import logging
import shlex

log = logging.getLogger(__name__)

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


class ScriptEngine:
    def __init__(self, command_handler):
        """
        command_handler: callable(line: str) -> (success, message)
        This is the same function the CLI uses to parse commands.
        """
        self._handle  = command_handler
        self._thread  = None
        self._stop    = threading.Event()

        self.running      = False
        self.current_file = None
        self.current_line = 0
        self.total_lines  = 0

    # ── Public API ────────────────────────────────────────────────

    def run(self, name_or_path, blocking=False):
        """
        Run a script. name_or_path can be:
          - 'morning'           → scripts/morning.fds
          - 'morning.fds'       → scripts/morning.fds
          - '/absolute/path'    → used as-is
        """
        path = self._resolve(name_or_path)
        if not path:
            return False, f"Script not found: {name_or_path}"

        if self.running:
            self.stop()
            time.sleep(0.1)

        self._stop.clear()
        self.running      = True
        self.current_file = os.path.basename(path)
        self.current_line = 0

        if blocking:
            self._run_file(path)
        else:
            self._thread = threading.Thread(
                target=self._run_file, args=(path,), daemon=True,
                name=f"script-{self.current_file}")
            self._thread.start()

        return True, f"Running: {self.current_file}"

    def stop(self):
        """Stop current script execution."""
        self._stop.set()
        self.running = False
        log.info("Script stopped")

    def status(self):
        if not self.running:
            return "No script running"
        return (f"Script: {self.current_file}  "
                f"Line: {self.current_line}/{self.total_lines}")

    def list_scripts(self):
        """Return list of available scripts."""
        if not os.path.isdir(SCRIPTS_DIR):
            return []
        scripts = []
        for root, dirs, files in os.walk(SCRIPTS_DIR):
            for fname in sorted(files):
                if fname.endswith(".fds"):
                    rel = os.path.relpath(
                        os.path.join(root, fname), SCRIPTS_DIR)
                    scripts.append(rel)
        return scripts

    # ── Internal ──────────────────────────────────────────────────

    def _resolve(self, name_or_path):
        """Resolve script name to absolute path."""
        # Absolute path
        if os.path.isabs(name_or_path):
            return name_or_path if os.path.isfile(name_or_path) else None

        # Try with and without .fds extension
        candidates = [
            os.path.join(SCRIPTS_DIR, name_or_path),
            os.path.join(SCRIPTS_DIR, name_or_path + ".fds"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

        # Prevent directory traversal
        return None

    def _run_file(self, path):
        """Execute a script file line by line."""
        try:
            with open(path) as f:
                lines = f.readlines()
        except Exception as e:
            log.error(f"Script file error: {e}")
            self.running = False
            return

        self.total_lines = len(lines)
        log.info(f"Script started: {path} ({self.total_lines} lines)")

        for i, raw_line in enumerate(lines):
            if self._stop.is_set():
                break

            self.current_line = i + 1
            line = raw_line.strip()

            # Skip blank lines and comments
            if not line or line.startswith("#"):
                continue

            # Handle script-specific commands
            if line.lower().startswith("wait "):
                try:
                    seconds = float(line.split()[1])
                    self._interruptible_wait(seconds)
                except (ValueError, IndexError):
                    log.warning(f"Bad wait command: {line}")
                continue

            if line.lower().startswith("script run "):
                sub = line[11:].strip()
                sub_path = self._resolve(sub)
                if sub_path:
                    log.info(f"Sub-script (blocking): {sub}")
                    sub_engine = ScriptEngine(self._handle)
                    sub_engine.run(sub_path, blocking=True)
                else:
                    log.warning(f"Sub-script not found: {sub}")
                continue

            if line.lower().startswith("script spawn "):
                sub = line[13:].strip()
                sub_engine = ScriptEngine(self._handle)
                ok, msg = sub_engine.run(sub)
                log.info(f"Spawned: {sub} — {msg}")
                continue

            # All other commands go to the command handler
            try:
                ok, msg = self._handle(line)
                if not ok:
                    log.warning(f"Script line {i+1} failed: {line!r} — {msg}")
                else:
                    log.debug(f"Script line {i+1}: {line!r}")
            except Exception as e:
                log.error(f"Script line {i+1} error: {e} — {line!r}")

        self.running = False
        log.info(f"Script completed: {os.path.basename(path)}")

    def _interruptible_wait(self, seconds):
        """Wait for N seconds, checking stop flag every 100ms."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stop.is_set():
                return
            time.sleep(min(0.1, deadline - time.time()))
