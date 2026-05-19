#!/usr/bin/env python3
"""
watchdog.py
-----------
Standalone watchdog. Starts flipdot.py and restarts it
if it exits for any reason.

This is what launchd actually runs. launchd then acts as
a watchdog for the watchdog itself.

Usage: python3 watchdog.py [--daemon] [--script overnight]
"""

import os
import sys
import time
import signal
import subprocess
import logging

BASE     = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE, "logs", "watchdog.log")
MAIN     = os.path.join(BASE, "flipdot.py")
VENV_PY  = os.path.join(BASE, ".venv", "bin", "python3")

# Use venv python if available, else system python
PYTHON = VENV_PY if os.path.isfile(VENV_PY) else sys.executable

os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("watchdog")

_running = True

def shutdown(signum, frame):
    global _running
    log.info("Watchdog shutting down")
    _running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT,  shutdown)


def main():
    # Pass all our args to flipdot.py
    extra_args = sys.argv[1:]
    cmd = [PYTHON, MAIN] + extra_args

    log.info(f"Watchdog started. Command: {' '.join(cmd)}")

    restart_count = 0
    last_start    = 0

    while _running:
        now     = time.time()
        uptime  = now - last_start if last_start else 0

        # If it died within 10 seconds, slow down restarts
        if last_start and uptime < 10:
            wait = min(30, 5 * (restart_count + 1))
            log.warning(f"Process died quickly (uptime {uptime:.1f}s). "
                        f"Waiting {wait}s before restart #{restart_count + 1}")
            time.sleep(wait)
        elif last_start:
            log.info(f"Restarting after {uptime:.0f}s uptime "
                     f"(restart #{restart_count + 1})")
            time.sleep(3)

        last_start = time.time()
        restart_count += 1

        log.info(f"Starting flipdot (attempt {restart_count})")
        try:
            proc = subprocess.Popen(cmd, cwd=BASE)
            proc.wait()
            exit_code = proc.returncode
            if exit_code == 0:
                log.info("FlipDot exited cleanly (code 0)")
            else:
                log.warning(f"FlipDot exited with code {exit_code}")
        except FileNotFoundError as e:
            log.error(f"Cannot start flipdot: {e}")
            time.sleep(30)
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
