"""
display.py — Serial connection with automatic reconnection.
If USB disconnects, reconnects automatically every 10 seconds.
Flipdots hold physical state with no power — display never goes blank.
"""
import threading
import time
import logging
import numpy as np

log = logging.getLogger(__name__)


class Display:
    def __init__(self, port, baud, layout):
        self.port   = port
        self.baud   = baud
        self.layout = layout
        self._ser   = None
        self._panel = None
        self._lock  = threading.Lock()
        self.W      = 84
        self.H      = 42
        self.buffer = np.zeros((42, 84), dtype=np.uint8)
        self.connected     = False
        self.connect_error = None
        self._running      = False
        self._thread       = None

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="display")
        self._thread.start()

    def stop(self):
        self._running = False
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass

    def _loop(self):
        while self._running:
            if not self.connected:
                self._connect()
            time.sleep(10)

    def _connect(self):
        try:
            import serial
            from flippydot import Panel
            ser   = serial.Serial(
                port=self.port, baudrate=self.baud,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=1.0)
            panel = Panel(self.layout, 28, 7,
                          module_rotation=0, screen_preview=False)
            with self._lock:
                self._ser         = ser
                self._panel       = panel
                self.W            = panel.get_total_width()
                self.H            = panel.get_total_height()
                self.buffer       = np.zeros((self.H, self.W), dtype=np.uint8)
                self.connected    = True
                self.connect_error= None
            log.info(f"Connected: {self.port} @ {self.baud} — {self.W}x{self.H}")
        except Exception as e:
            self.connect_error = str(e)
            self.connected     = False
            log.warning(f"Connection failed: {e}")

    def reconnect(self, port=None, baud=None):
        if port:
            self.port = port
        if baud:
            self.baud = int(baud)
        with self._lock:
            self.connected = False
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        self._connect()

    def send(self, frame):
        with self._lock:
            if not self.connected or self._ser is None:
                return False
            try:
                data = self._panel.apply_frame(frame)
                if isinstance(data, np.ndarray):
                    raw = b"".join(data.flatten().tolist())
                else:
                    raw = bytes(data)
                self._ser.write(raw)
                self.buffer = frame.copy()
                return True
            except Exception as e:
                log.warning(f"Send failed: {e}")
                self.connected = False
                return False

    def clear(self):
        frame = np.zeros((self.H, self.W), dtype=np.uint8)
        self.buffer = frame
        self.send(frame)

    def fill(self):
        frame = np.ones((self.H, self.W), dtype=np.uint8)
        self.buffer = frame
        self.send(frame)
