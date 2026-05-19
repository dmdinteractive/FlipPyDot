"""
wizard.py
---------
Panel mapping wizard — lights one controller at a time so the user
can click its position in the browser grid.

Uses direct serial writes with the correct 0x83 command byte,
reusing the already-open serial connection from app.py.
"""

import time
import logging

log = logging.getLogger(__name__)

ALL_ON  = 0x7F  # All 7 dots white
ALL_OFF = 0x00  # All 7 dots black
CMD     = 0x83  # AlfaZeta show-now command


class PanelWizard:

    def __init__(self, get_serial_fn, total=18):
        """
        get_serial_fn: callable that returns the open serial.Serial object
        total:         number of controllers to map
        """
        self._get_ser    = get_serial_fn
        self.total       = total
        self.current     = None
        self.mappings    = {}   # address -> {"row": r, "col": c, "half": "top"|"bottom"}
        self.active      = False

    # ── Serial helpers ────────────────────────────────────────────

    def _write(self, address: int, value: int):
        ser = self._get_ser()
        if ser is None or not ser.is_open:
            log.warning("Wizard: serial not available")
            return False
        try:
            frame = bytes([0x80, CMD, address] + [value] * 28 + [0x8F])
            ser.write(frame)
            return True
        except Exception as e:
            log.error(f"Wizard write error: {e}")
            return False

    def _clear_all(self):
        for addr in range(self.total):
            self._write(addr, ALL_OFF)
            time.sleep(0.02)

    def _light(self, address: int):
        self._clear_all()
        time.sleep(0.1)
        self._write(address, ALL_ON)
        log.info(f"Wizard: lit address {address}")

    # ── Wizard flow ───────────────────────────────────────────────

    def start(self, total: int = None):
        if total: self.total = total
        self.mappings = {}
        self.current  = 0
        self.active   = True
        self._light(0)
        return {"success": True, "current": 0, "total": self.total}

    def assign(self, address: int, col: int, row: int, half: str):
        """Record address → position and advance."""
        self.mappings[address] = {"col": col, "row": row, "half": half}
        log.info(f"Wizard: addr {address} → col{col} row{row} {half}")

        nxt = address + 1
        if nxt < self.total:
            self.current = nxt
            self._light(nxt)
            return {"success": True, "mapped": len(self.mappings),
                    "total": self.total, "next": nxt, "complete": False}
        else:
            self.current = None
            self.active  = False
            self._clear_all()
            return {"success": True, "mapped": len(self.mappings),
                    "total": self.total, "complete": True}

    def skip(self, address: int):
        nxt = address + 1
        if nxt < self.total:
            self.current = nxt
            self._light(nxt)
        else:
            self.active  = False
            self.current = None
            self._clear_all()
        return {"success": True, "next": nxt, "complete": nxt >= self.total}

    def stop(self):
        self.active  = False
        self.current = None
        self._clear_all()
        return {"success": True}

    def build_layout(self):
        """
        Convert mappings to a flipPyDot LAYOUT 2D array.
        Returns a 6-row × 3-col list of address integers.
        """
        # Determine grid size from mappings
        rows = set(); cols = set()
        for m in self.mappings.values():
            rows.add((m["row"], m["half"]))
            cols.add(m["col"])

        num_pcols = max(m["col"]  for m in self.mappings.values()) if self.mappings else 3
        num_prows = max(m["row"]  for m in self.mappings.values()) if self.mappings else 3

        # 2D grid: [controller_row][controller_col]
        # physical row 1 top = controller row 0
        # physical row 1 bottom = controller row 1  etc.
        ctrl_rows = num_prows * 2
        ctrl_cols = num_pcols
        grid = [[0] * ctrl_cols for _ in range(ctrl_rows)]

        for addr, m in self.mappings.items():
            c    = m["col"] - 1                          # 0-indexed
            r    = (m["row"] - 1) * 2 + (0 if m["half"] == "top" else 1)
            if 0 <= r < ctrl_rows and 0 <= c < ctrl_cols:
                grid[r][c] = addr

        return grid

    def get_state(self):
        return {
            "active":    self.active,
            "current":   self.current,
            "mapped":    len(self.mappings),
            "total":     self.total,
            "mappings":  self.mappings,
        }
