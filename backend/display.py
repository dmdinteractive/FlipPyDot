"""
display.py
----------
Serial connection manager with automatic reconnection.

Responsibilities:
  - Open and maintain the RS485 serial connection
  - Detect disconnection and reconnect automatically
  - Send frames to the hardware via flippydot Panel
  - Maintain a virtual display buffer
  - Provide thread-safe frame operations

The reconnection loop runs in a background thread. If the USB adapter
is unplugged and replugged, the connection restores without any operator
action. Flipdots hold their physical state with no power, so the display
does not go blank during reconnection.
"""

import os
import sys
import time
import threading
import logging
import numpy as np

log = logging.getLogger(__name__)

# Default display dimensions — used before connection is established
DEFAULT_W = 84
DEFAULT_H = 42


class Display:
    """
    Manages the flipdot display hardware connection and buffer.

    Usage:
        d = Display(port, baud, layout)
        d.start()           # begin connection + reconnection loop
        d.send(frame)       # send numpy uint8 array to hardware
        d.stop()            # clean shutdown
    """

    RECONNECT_DELAYS = [5, 10, 20, 40, 60]  # exponential backoff seconds

    def __init__(self, port, baud, layout):
        self.port   = port
        self.baud   = baud
        self.layout = layout

        self._ser    = None
        self._panel  = None
        self._lock   = threading.Lock()
        self._thread = None
        self._running= False

        self.W = DEFAULT_W
        self.H = DEFAULT_H
        self.buffer = np.zeros((self.H, self.W), dtype=np.uint8)

        self.connected     = False
        self.connect_error = None
        self.reconnect_count = 0

        # Callbacks
        self.on_connect    = None   # called when connection established
        self.on_disconnect = None   # called when connection lost

    # ── Public API ────────────────────────────────────────────────

    def start(self):
        """Start the connection manager thread."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._connection_loop, daemon=True, name="display-conn")
        self._thread.start()

    def stop(self):
        """Shutdown cleanly."""
        self._running = False
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.close()
                except Exception:
                    pass
        log.info("Display stopped")

    def send(self, frame):
        """
        Send a numpy uint8 frame to the hardware.
        Returns True on success, False if not connected.
        """
        with self._lock:
            if not self.connected or self._ser is None or not self._ser.is_open:
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
                self._mark_disconnected()
                return False

    def get_buffer(self):
        """Return the current display buffer."""
        return self.buffer.copy()

    def set_port(self, port):
        """Update the serial port. Takes effect on next reconnection."""
        self.port = port

    def update_layout(self, layout):
        """Update panel layout. Takes effect on next reconnection."""
        self.layout = layout

    # ── Connection loop ───────────────────────────────────────────

    def _connection_loop(self):
        """
        Runs in background thread.
        Connects, monitors health, reconnects on failure.
        """
        attempt = 0
        while self._running:
            if not self.connected:
                delay = self.RECONNECT_DELAYS[
                    min(attempt, len(self.RECONNECT_DELAYS) - 1)]
                if attempt > 0:
                    log.info(f"Reconnecting in {delay}s (attempt {attempt})...")
                    time.sleep(delay)
                success = self._connect()
                if success:
                    attempt = 0
                else:
                    attempt += 1
            else:
                # Health check — try a no-op to detect silent disconnects
                time.sleep(5)
                if not self._health_check():
                    self._mark_disconnected()

    def _connect(self):
        """Attempt to open the serial connection."""
        try:
            import serial
            from flippydot import Panel

            ser = serial.Serial(
                port      = self.port,
                baudrate  = self.baud,
                bytesize  = serial.EIGHTBITS,
                parity    = serial.PARITY_NONE,
                stopbits  = serial.STOPBITS_ONE,
                timeout   = 1.0,
            )
            panel = Panel(self.layout, 28, 7,
                          module_rotation=0, screen_preview=False)

            with self._lock:
                self._ser   = ser
                self._panel = panel
                self.W      = panel.get_total_width()
                self.H      = panel.get_total_height()
                self.buffer = np.zeros((self.H, self.W), dtype=np.uint8)
                self.connected     = True
                self.connect_error = None
                self.reconnect_count += 1

            log.info(f"Connected: {self.port} @ {self.baud} — {self.W}x{self.H}")
            if self.on_connect:
                self.on_connect()
            return True

        except Exception as e:
            self.connect_error = str(e)
            log.warning(f"Connection failed: {e}")
            return False

    def _health_check(self):
        """Return False if connection appears dead."""
        with self._lock:
            if self._ser is None:
                return False
            try:
                return self._ser.is_open
            except Exception:
                return False

    def _mark_disconnected(self):
        """Mark as disconnected so the loop tries to reconnect."""
        with self._lock:
            self.connected = False
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        log.warning("Display disconnected — will reconnect automatically")
        if self.on_disconnect:
            self.on_disconnect()

    # ── Convenience draw methods ──────────────────────────────────

    def clear(self):
        frame = np.zeros((self.H, self.W), dtype=np.uint8)
        self.buffer = frame
        self.send(frame)

    def fill(self):
        frame = np.ones((self.H, self.W), dtype=np.uint8)
        self.buffer = frame
        self.send(frame)

    def push_buffer(self, buf):
        """Send an arbitrary buffer (list of lists or numpy array)."""
        frame = np.array(buf, dtype=np.uint8)
        self.buffer = frame
        self.send(frame)
