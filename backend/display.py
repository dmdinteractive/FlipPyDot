"""
display.py — Getting frames onto the panel, as fast as the wire allows and
never faster.

WHY THIS FILE EXISTS
────────────────────
V8 handed every frame to the flippydot library, which re-encoded all 18
controllers and wrote them with the "show now" command (0x83). Two problems:

  1. BACKLOG. pyserial's write() returns as soon as the bytes are in the
     operating system's buffer, not when they've left the wire. If software
     produces frames faster than 57600 baud can carry them, they pile up in
     that buffer and the panel falls further and further behind real time.

  2. WASTE. Every frame re-sent every controller, even ones whose dots had
     not changed. A one-line scroll touches 3 of 18 controllers.

HOW THIS VERSION WORKS
──────────────────────
    player ──send(frame)──▶ [ mailbox: newest frame only ] ──▶ pump thread ──▶ bus 1..N

  * The mailbox holds ONE frame. Posting a new frame replaces the old one
    unsent. The producer never waits on the serial port, and stale frames
    are discarded rather than queued — so a backlog is impossible by design.

  * The pump takes the newest frame, works out which controllers actually
    changed since the last write, and sends only those.

  * Each write is PACED: we wait until the bytes have physically left the
    wire (flush + bytes×10/baud) before the pump looks for the next frame.
    The pump therefore runs exactly as fast as the hardware can go.

  * "Synced" write mode uses 0x84 (load buffer, don't flip) for each changed
    controller and then one 0x82 (flip everything now). The whole panel
    changes in the same instant instead of tearing top-to-bottom. "Immediate"
    mode uses 0x83 exactly like V8 did — kept as the default because it's
    proven on this installation; switch modes from Setup → Hardware.

  * Up to four USB-RS485 adapters ("buses") can share the work. Each
    controller is assigned to a bus; all buses are written in parallel, so
    three buses of six controllers carry three times the frames per second.

  * Every RESYNC_S seconds everything is re-sent once, so a controller that
    was power-cycled or missed a packet heals itself without anyone noticing.

Protocol reference (AlfaZeta XY5, 7x28 controller):
    0x80  CMD  ADDR  <28 data bytes>  0x8F
    CMD 0x83 = write + show,  0x84 = write to buffer only
    0x80 0x82 0x8F = show buffered data on every controller
    Data byte n = column n, bit 0 = top dot ... bit 6 = bottom dot.
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

log = logging.getLogger(__name__)

MOD_W, MOD_H = 28, 7
BYTES_PER_MODULE = 32                 # 0x80, cmd, addr, 28 data, 0x8F
CMD_SHOW, CMD_BUFFER = 0x83, 0x84
REFRESH = bytes([0x80, 0x82, 0x8F])
MAX_BUSES = 4

WRITE_MODES = ("immediate", "synced")


def encode(frame, rows, cols):
    """(rows*7, cols*28) frame -> (rows, cols, 28) controller data bytes.

    Byte-for-byte identical to flippydot 0.1.1's packbits(axis=0,
    bitorder='little'), just vectorised over the whole panel at once.
    """
    f = (np.asarray(frame, dtype=np.uint8) & 1).reshape(rows, MOD_H, cols, MOD_W)
    weights = (1 << np.arange(MOD_H, dtype=np.uint8)).reshape(1, MOD_H, 1, 1)
    return (f * weights).sum(axis=1, dtype=np.uint16).astype(np.uint8)


def packet(cmd, addr, data28):
    return bytes([0x80, cmd, int(addr) & 0xFF]) + bytes(data28) + b"\x8f"


# ──────────────────────────────────────────────────────────────────
class Bus:
    """One USB-RS485 adapter."""

    def __init__(self, idx, port, baud):
        self.idx   = idx
        self.port  = port
        self.baud  = int(baud)
        self.ser   = None
        self.error = None
        self.lock  = threading.Lock()     # one writer at a time (pump vs wizard)
        self.open_lock = threading.Lock() # watchdog and reconnect() can race
        self.bytes_sent = 0

    @property
    def connected(self):
        return self.ser is not None

    def open(self):
        with self.open_lock:
            return self._open()

    def _open(self):
        self.close()
        try:
            import serial
            self.ser = serial.Serial(
                port=self.port, baudrate=self.baud,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=1.0, write_timeout=2.0)
            self.error = None
            log.info(f"Bus {self.idx + 1}: connected {self.port} @ {self.baud}")
            return True
        except Exception as e:
            self.ser   = None
            self.error = str(e)
            log.warning(f"Bus {self.idx + 1}: {self.port} failed — {e}")
            return False

    def close(self):
        with self.lock:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    def write(self, data):
        """Write and wait until the bytes have physically left the wire.

        flush() waits for the OS buffer to drain; the USB adapter has its own
        small FIFO on top of that, so we also wait out the theoretical wire
        time from the start of the write. Either way, when this returns the
        line is idle — which is what keeps the next frame from queueing.
        """
        if not data:
            return True
        with self.lock:
            if self.ser is None:
                return False
            t0 = time.monotonic()
            try:
                self.ser.write(data)
                self.ser.flush()
            except Exception as e:
                log.warning(f"Bus {self.idx + 1}: write failed — {e}")
                self.error = str(e)
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                return False
            wire = len(data) * 10.0 / self.baud
            left = wire - (time.monotonic() - t0)
            if left > 0:
                time.sleep(left)
            self.bytes_sent += len(data)
            return True


# ──────────────────────────────────────────────────────────────────
class Display:
    RESYNC_S    = 30.0      # full re-send interval, self-heals missed packets
    RECONNECT_S = 5.0

    def __init__(self, layout, buses, bus_map=None, write_mode="immediate",
                 max_fps=20.0):
        """
        layout  — grid of controller addresses, one row per 7-dot strip.
        buses   — [{"port": ..., "baud": ...}, ...]  (1 to 4 adapters)
        bus_map — grid the same shape as layout: which bus each controller
                  is wired to. None = everything on bus 0.
        """
        self._cfg_lock   = threading.RLock()
        self._mail_lock  = threading.Condition()
        self._latest     = None
        self._latest_seq = 0
        self._sent_seq   = 0
        self.buffer      = None
        self._running    = False
        self._pump       = None
        self._watch      = None
        self._pool       = None
        self._force      = True
        self.paused      = False   # panel wizard owns the wire while True
        self.manual_off  = False   # Disconnect pressed: watchdog stays out
        self._stats      = {"fps": 0.0, "modules": 0.0, "skipped": 0,
                            "frames": 0, "last": 0.0}
        self.configure(layout, buses, bus_map, write_mode, max_fps)

    # ── configuration ─────────────────────────────────────────────
    def configure(self, layout=None, buses=None, bus_map=None,
                  write_mode=None, max_fps=None):
        with self._cfg_lock:
            if layout is not None:
                self.layout = [list(map(int, r)) for r in layout]
            self.rows = len(self.layout)
            self.cols = max((len(r) for r in self.layout), default=0)
            self.W, self.H = self.cols * MOD_W, self.rows * MOD_H

            if buses is not None:
                old = getattr(self, "buses", [])
                for b in old:
                    b.close()
                buses = list(buses)[:MAX_BUSES] or [{"port": "", "baud": 57600}]
                self.buses = [Bus(i, b.get("port", ""), b.get("baud", 57600))
                              for i, b in enumerate(buses)]
                old_pool = self._pool
                self._pool = ThreadPoolExecutor(max_workers=len(self.buses),
                                                thread_name_prefix="bus")
                if old_pool is not None:
                    old_pool.shutdown(wait=False)

            if bus_map is not None or not hasattr(self, "bus_map"):
                self.bus_map = self._clean_map(bus_map)
            else:
                self.bus_map = self._clean_map(self.bus_map)

            if write_mode in WRITE_MODES:
                self.write_mode = write_mode
            elif not hasattr(self, "write_mode"):
                self.write_mode = "immediate"

            if max_fps:
                self.max_fps = max(1.0, min(60.0, float(max_fps)))

            self._last = None              # per-controller last-sent bytes
            self._force = True
            if self.buffer is None or self.buffer.shape != (self.H, self.W):
                # Panel changed shape: anything in the mailbox is now the
                # wrong size and can't be encoded. Start from blank.
                blank = np.zeros((self.H, self.W), dtype=np.uint8)
                with self._mail_lock:
                    self.buffer = blank
                    if self._latest is not None:
                        self._latest = blank
                        self._latest_seq += 1
                        self._mail_lock.notify_all()

    def _clean_map(self, m):
        out = []
        n = len(getattr(self, "buses", [None]))
        for r, row in enumerate(self.layout):
            src = (m[r] if m and r < len(m) else [])
            out.append([int(src[c]) if c < len(src) and 0 <= int(src[c]) < n else 0
                        for c in range(len(row))])
        return out

    # ── compatibility surface used by app.py / wizard ─────────────
    @property
    def connected(self):
        return any(b.connected for b in self.buses)

    @property
    def connect_error(self):
        errs = [f"bus {b.idx + 1}: {b.error}" for b in self.buses if b.error]
        return "; ".join(errs) or None

    @property
    def port(self):
        return self.buses[0].port

    @property
    def baud(self):
        return self.buses[0].baud

    @property
    def module_count(self):
        return sum(len(r) for r in self.layout) or 1

    def bus_modules(self, i):
        return sum(1 for row in self.bus_map for b in row if b == i)

    def wire_fps(self):
        """Worst-case full-frame rate: the busiest bus decides."""
        worst = 0.0
        for b in self.buses:
            n = self.bus_modules(b.idx)
            if not n:
                continue
            bytes_ = n * BYTES_PER_MODULE + (len(REFRESH) if self.write_mode == "synced" else 0)
            t = bytes_ * 10.0 / max(1, b.baud)
            worst = max(worst, t)
        return (1.0 / worst) if worst else self.max_fps

    # ── lifecycle ─────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._pump  = threading.Thread(target=self._pump_loop, daemon=True, name="pump")
        self._watch = threading.Thread(target=self._watch_loop, daemon=True, name="buswatch")
        self._pump.start()
        self._watch.start()

    def request_resync(self):
        with self._cfg_lock:
            self._force = True

    def stop(self):
        """Close every adapter and keep them closed (frees the port for other
        tools) until reconnect() is called."""
        self.manual_off = True
        for b in self.buses:
            b.close()

    def shutdown(self):
        self._running = False
        with self._mail_lock:
            self._mail_lock.notify_all()
        self.stop()

    def reconnect(self, buses=None, **kw):
        if buses is not None or kw:
            self.configure(buses=buses, **kw)
        self.manual_off = False
        for b in self.buses:
            if b.port:
                b.open()
        self.request_resync()

    def _watch_loop(self):
        while self._running:
            if not self.manual_off and not self.paused:
                for b in list(self.buses):
                    if not b.connected and b.port:
                        if b.open():
                            self.request_resync()
            time.sleep(self.RECONNECT_S)

    # ── the producer side ─────────────────────────────────────────
    def send(self, frame):
        """Post a frame. Never blocks. If the pump hasn't picked up the
        previous frame yet, that one is simply replaced — it's stale."""
        frame = np.asarray(frame, dtype=np.uint8)
        if frame.shape != (self.H, self.W):
            fixed = np.zeros((self.H, self.W), dtype=np.uint8)
            h, w = min(self.H, frame.shape[0]), min(self.W, frame.shape[1])
            fixed[:h, :w] = frame[:h, :w]
            frame = fixed
        with self._mail_lock:
            if self._latest is not None and self._latest_seq != self._sent_seq:
                self._stats["skipped"] += 1
            self._latest = frame.copy()
            self._latest_seq += 1
            self.buffer = self._latest
            self._mail_lock.notify_all()
        return True

    def clear(self):
        self.send(np.zeros((self.H, self.W), dtype=np.uint8))

    def fill(self):
        self.send(np.ones((self.H, self.W), dtype=np.uint8))

    def wait_frame(self, after_seq, timeout=1.0):
        """For the live monitor: block until a frame newer than after_seq."""
        with self._mail_lock:
            if self._latest_seq == after_seq:
                self._mail_lock.wait(timeout)
            return self._latest_seq, self.buffer

    # ── the pump ──────────────────────────────────────────────────
    def _pump_loop(self):
        last_out = 0.0
        last_resync = time.monotonic()
        ema = None
        while self._running:
            if self.paused:
                time.sleep(0.1)
                continue
            # Respect the mechanical frame limit BEFORE taking a frame, so the
            # frame we take is the freshest one available when we're allowed
            # to send.
            gap = (1.0 / self.max_fps) - (time.monotonic() - last_out)
            if gap > 0:
                time.sleep(gap)

            with self._mail_lock:
                while (self._running and self._latest_seq == self._sent_seq
                       and not self._force
                       and time.monotonic() - last_resync < self.RESYNC_S):
                    self._mail_lock.wait(0.5)
                if not self._running:
                    return
                frame = self._latest
                seq   = self._latest_seq
            if time.monotonic() - last_resync >= self.RESYNC_S:
                self.request_resync()
                last_resync = time.monotonic()

            if frame is None or frame.shape != (self.H, self.W):
                self._sent_seq = seq
                continue

            started = time.monotonic()
            try:
                sent_modules = self._write_frame(frame)
            except Exception as e:
                log.error(f"Pump error: {e}", exc_info=True)
                sent_modules = 0
                time.sleep(0.2)
            self._sent_seq = seq

            if sent_modules:
                # The frame limit is start-to-start: a frame that took 30 ms
                # on the wire only waits out the rest of the frame period.
                now = started
                if last_out:
                    inst = 1.0 / max(1e-3, now - last_out)
                    ema = inst if ema is None else ema * 0.85 + inst * 0.15
                    self._stats["fps"] = round(ema, 1)
                self._stats["modules"] = round(
                    self._stats["modules"] * 0.85 + sent_modules * 0.15, 1)
                self._stats["frames"] += 1
                self._stats["last"] = time.time()
                last_out = now

    def _write_frame(self, frame):
        with self._cfg_lock:
            rows, cols = self.rows, self.cols
            layout, bus_map, buses = self.layout, self.bus_map, self.buses
            mode = self.write_mode
            data = encode(frame, rows, cols)
            if self._last is None or self._last.shape != data.shape:
                self._last = np.full(data.shape, 0xFF, dtype=np.uint16)  # impossible value
                self._force = True
            force = self._force
            self._force = False
            last = self._last

        cmd = CMD_BUFFER if mode == "synced" else CMD_SHOW
        jobs = {b.idx: [] for b in buses}
        for r in range(rows):
            for c in range(len(layout[r])):
                if force or not np.array_equal(data[r, c], last[r, c]):
                    jobs[bus_map[r][c]].append((r, c, packet(cmd, layout[r][c], data[r, c])))

        work = [(b, jobs[b.idx]) for b in buses if jobs[b.idx] and b.connected]
        if not work:
            return 0

        def run(item):
            b, items = item
            ok = b.write(b"".join(p for _, _, p in items))
            return b, items, ok

        results = list(self._pool.map(run, work)) if len(work) > 1 else [run(work[0])]

        if mode == "synced":
            # Flip every controller at the same instant. Sent on every bus that
            # took data, in parallel, so they land within a millisecond.
            flips = [b for b, _, ok in results if ok]
            if len(flips) > 1:
                list(self._pool.map(lambda b: b.write(REFRESH), flips))
            elif flips:
                flips[0].write(REFRESH)

        count = 0
        for b, items, ok in results:
            if ok:
                for r, c, _ in items:
                    last[r, c] = data[r, c]
                count += len(items)
            else:
                self.request_resync()     # resend everything once it's back
        return count

    # ── raw access for the panel wizard ───────────────────────────
    def write_raw_all(self, data):
        ok = False
        for b in self.buses:
            ok = b.write(data) or ok
        self.request_resync()             # wizard scribbled on the panel
        return ok

    # ── status ────────────────────────────────────────────────────
    def get_status(self):
        return {
            "write_mode": self.write_mode,
            "max_fps":    self.max_fps,
            "wire_fps":   round(self.wire_fps(), 1),
            "fps":        self._stats["fps"] if time.time() - self._stats["last"] < 2 else 0.0,
            "modules_per_frame": self._stats["modules"],
            "skipped":    self._stats["skipped"],
            "frames":     self._stats["frames"],
            "bus_map":    self.bus_map,
            "layout":     self.layout,
            "buses": [{
                "index":     b.idx,
                "port":      b.port,
                "baud":      b.baud,
                "connected": b.connected,
                "error":     b.error,
                "modules":   self.bus_modules(b.idx),
                "bytes_sent": b.bytes_sent,
            } for b in self.buses],
        }
