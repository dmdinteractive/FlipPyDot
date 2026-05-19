#!/usr/bin/env python3
"""
flipdot.py — FlipDot CLI Console
---------------------------------
Usage:
  python3 flipdot.py                     — interactive mode
  python3 flipdot.py --script morning    — run script then interactive
  python3 flipdot.py --daemon            — daemon mode, no prompt
  python3 flipdot.py --daemon --script overnight
  python3 flipdot.py --setup             — run first-time config setup
"""

import os
import sys
import time
import signal
import logging
import logging.handlers
import argparse
import threading
import socket

# ── Paths ─────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "backend"))

# ── Logging setup ─────────────────────────────────────────────────
LOG_DIR  = os.path.join(BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "flipdot.log")
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(level)

    # Rotating file handler — 5MB, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    # Console handler for interactive mode
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)   # Only warnings+ to console
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(ch)

log = logging.getLogger("flipdot")

# ── ANSI helpers ──────────────────────────────────────────────────
ESC   = "\033["
CLEAR_LINE  = ESC + "2K\r"
CURSOR_UP   = ESC + "1A"
CURSOR_SAVE = ESC + "s"
CURSOR_RESTORE = ESC + "u"
BOLD  = ESC + "1m"
DIM   = ESC + "2m"
RESET = ESC + "0m"
ITALIC= ESC + "3m"

def _ansi(code, text):
    return f"{ESC}{code}m{text}{RESET}"

def bold(t):   return _ansi("1", t)
def dim(t):    return _ansi("2", t)
def italic(t): return _ansi("3", t)


# ── Status header ─────────────────────────────────────────────────
class StatusHeader:
    """
    Draws a 3-line status header at the top of the terminal.
    Redraws in place using ANSI escape codes.
    """
    HEIGHT = 4   # lines the header occupies

    def __init__(self, engine):
        self.engine  = engine
        self._lock   = threading.Lock()
        self._thread = None
        self._stop   = threading.Event()

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="status-header")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        # Print initial blank lines to make room
        print("\n" * self.HEIGHT)
        while not self._stop.is_set():
            self._draw()
            time.sleep(0.5)

    def _draw(self):
        with self._lock:
            try:
                st  = self.engine.status_dict()
                eng = st["cue_engine"]
                cur = eng.get("current_cue")
                sng = self.engine.script_engine

                line1 = (
                    f" {bold('FLIPDOT')}  │  "
                    f"{'● CONNECTED' if st['connected'] else '○ OFFLINE'}  "
                    f"{dim(st['port'])}  │  "
                    f"{st['dimensions']}  │  "
                    f"{dim(time.strftime('%H:%M:%S'))}"
                )
                line2 = (
                    f" CUE: "
                    f"{bold(str(cur['number'])) if cur else dim('—')}  "
                    f"{cur['label'] if cur else dim('NO CUE ACTIVE')}  │  "
                    f"STATE: {bold(eng['state'])}  │  "
                    f"ELAPSED: {dim(str(round(eng.get('elapsed', 0), 1))+'s')}"
                )
                sched_str = "SCHED: " + ("RUNNING" if st["scheduler"]["running"] else dim("OFF"))
                pl_str    = "PLAYLIST: " + (
                    st["playlist"]["mode"].upper() if st["playlist"]["running"] else dim("OFF"))
                scr_str   = f"SCRIPT: {sng.current_file}" if sng.running else ""
                line3     = f" {sched_str}  │  {pl_str}" + (f"  │  {scr_str}" if scr_str else "")

                sep = dim("─" * 72)

                # Move cursor up HEIGHT lines and redraw
                sys.stdout.write(
                    f"{ESC}{self.HEIGHT + 1}A"  # move up
                    f"\r{CLEAR_LINE}{line1}\n"
                    f"\r{CLEAR_LINE}{line2}\n"
                    f"\r{CLEAR_LINE}{line3}\n"
                    f"\r{CLEAR_LINE}{sep}\n"
                    f"\r"
                )
                sys.stdout.flush()
            except Exception:
                pass


# ── Daemon socket listener ────────────────────────────────────────
SOCKET_PATH = "/tmp/flipdot.sock"

class DaemonSocket:
    """
    Listens on a Unix socket for remote commands.
    Allows: echo "go 3" | nc -U /tmp/flipdot.sock
    """
    def __init__(self, handler):
        self._handler = handler
        self._thread  = None
        self._server  = None

    def start(self):
        # Remove stale socket
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(SOCKET_PATH)
        self._server.listen(5)
        self._server.settimeout(1.0)
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="daemon-socket")
        self._thread.start()
        log.info(f"Daemon socket: {SOCKET_PATH}")

    def stop(self):
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

    def _loop(self):
        while True:
            try:
                conn, _ = self._server.accept()
                threading.Thread(
                    target=self._handle_conn, args=(conn,),
                    daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                log.debug(f"Socket loop: {e}")
                break

    def _handle_conn(self, conn):
        try:
            data = conn.recv(4096).decode("utf-8", errors="replace").strip()
            if data:
                for line in data.splitlines():
                    line = line.strip()
                    if line:
                        ok, msg = self._handler(line)
                        response = f"{'OK' if ok else 'ERR'}: {msg}\n"
                        conn.sendall(response.encode())
        except Exception as e:
            log.debug(f"Socket conn: {e}")
        finally:
            conn.close()


# ── Main application ──────────────────────────────────────────────
class FlipDotApp:
    def __init__(self, args):
        self.args    = args
        self.engine  = None
        self.handler = None
        self.header  = None
        self.daemon_sock = None
        self._running = True

    def run(self):
        # Load config
        import config as cfg_mod
        config  = cfg_mod.load("config")
        layout  = cfg_mod.load("layout")
        varcfg  = cfg_mod.load("variables")

        # First-run setup
        if self.args.setup or not config.get("port"):
            cfg_mod.setup_interactive()
            config = cfg_mod.load("config")
            layout = cfg_mod.load("layout")
            varcfg = cfg_mod.load("variables")

        # Build display
        from display import Display
        display = Display(
            port   = config["port"],
            baud   = int(config["baud_rate"]),
            layout = layout if isinstance(layout, list) else layout.get("layout",
                     [[0,2,4],[1,3,5],[6,8,10],[7,9,11],[12,14,16],[13,15,17]]),
        )

        # Build engine
        from engine  import Engine
        from script_engine import ScriptEngine
        from commands import CommandHandler

        self.engine                = Engine(display)
        self.engine.var_mod.configure(varcfg)

        script_eng                 = ScriptEngine(None)  # handler set below
        self.engine.script_engine  = script_eng

        self.handler = CommandHandler(self.engine)
        script_eng._handle = self.handler.handle

        # Startup
        display.start()
        self.engine.start()

        # Give serial a moment to connect
        time.sleep(1.0)

        # Load default show if exists
        default_show = os.path.join(BASE, "shows", "default.yaml")
        if os.path.isfile(default_show):
            try:
                self.engine.show_mgr.load_show(
                    "default", self.engine.cue_eng, self.engine.scheduler)
                log.info("Default show loaded")
            except Exception as e:
                log.warning(f"Could not load default show: {e}")

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGTERM, self._shutdown_signal)
        signal.signal(signal.SIGINT,  self._shutdown_signal)

        # Write PID file
        pid_file = "/tmp/flipdot.pid"
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

        # Run startup script if specified
        if self.args.script:
            ok, msg = script_eng.run(self.args.script)
            log.info(f"Startup script: {msg}")
            if not ok:
                print(f"Warning: {msg}")

        if self.args.daemon:
            self._run_daemon()
        else:
            self._run_interactive()

    def _run_daemon(self):
        """Daemon mode — no prompt, controlled via Unix socket."""
        log.info("Running in daemon mode")
        print(f"FlipDot daemon running. PID: {os.getpid()}")
        print(f"Control via: echo 'command' | nc -U {SOCKET_PATH}")

        self.daemon_sock = DaemonSocket(self.handler.handle)
        self.daemon_sock.start()

        try:
            while self._running:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._shutdown()

    def _run_interactive(self):
        """Interactive mode — readline prompt with status header."""
        import readline

        # Tab completion
        commands = [
            "text", "scroll", "fill", "clear", "image", "gif",
            "anim", "go", "back", "hold", "release",
            "cue", "sched", "playlist", "fx", "vars", "preview",
            "assets", "show", "script", "connect", "disconnect",
            "ports", "status", "log", "test", "pixel", "update", "help",
        ]
        def completer(text, state):
            options = [c for c in commands if c.startswith(text)]
            return options[state] if state < len(options) else None
        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")

        # Start status header
        self.header = StatusHeader(self.engine)

        # Start daemon socket even in interactive mode
        self.daemon_sock = DaemonSocket(self.handler.handle)
        self.daemon_sock.start()

        self.header.start()

        print()  # Space below header

        try:
            while self._running:
                try:
                    line = input(f"{dim('flipdot')}> ")
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print()
                    continue

                line = line.strip()
                if not line:
                    continue

                if line.lower() in ("quit", "exit", "q"):
                    break

                ok, msg = self.handler.handle(line)
                if msg:
                    prefix = "" if ok else f"{ESC}31m! {RESET}"
                    print(f"{prefix}{msg}")
                    print()

        except Exception as e:
            log.error(f"Interactive loop error: {e}", exc_info=True)
        finally:
            self._shutdown()

    def _shutdown_signal(self, signum, frame):
        log.info(f"Signal received: {signum}")
        self._running = False
        self._shutdown()
        sys.exit(0)

    def _shutdown(self):
        log.info("Shutting down...")
        if self.header:
            self.header.stop()
        if self.daemon_sock:
            self.daemon_sock.stop()
        if self.engine:
            # Save current state as default show
            try:
                import config as cfg_mod
                c = cfg_mod.load("config")
                l = cfg_mod.load("layout")
                self.engine.show_mgr.save_show(
                    "default", self.engine.cue_eng, self.engine.scheduler,
                    {"port": c["port"], "baud_rate": c["baud_rate"], "layout": l})
                log.info("State saved as default show")
            except Exception as e:
                log.warning(f"Could not save state: {e}")
            self.engine.stop()
            self.engine.display.stop()
        # Remove PID file
        if os.path.exists("/tmp/flipdot.pid"):
            os.remove("/tmp/flipdot.pid")
        log.info("Shutdown complete")


# ── Entry point ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="FlipDot CLI Console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--daemon",  action="store_true",
                        help="Run in daemon mode (no interactive prompt)")
    parser.add_argument("--script",  type=str, default=None,
                        help="Run a script on startup (e.g. --script overnight)")
    parser.add_argument("--setup",   action="store_true",
                        help="Run first-time configuration setup")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose logging")
    parser.add_argument("--version", action="store_true",
                        help="Print version and exit")

    args = parser.parse_args()

    if args.version:
        print("FlipDot CLI v1.0")
        sys.exit(0)

    setup_logging(args.verbose)
    log.info("FlipDot CLI starting")

    app = FlipDotApp(args)
    app.run()


if __name__ == "__main__":
    main()
