#!/usr/bin/env python3
"""
flipdot.py
----------
Simple flipdot controller built directly on flipPyDot.
No web server, no frameworks — just reliable serial communication.

Run from the project folder:
    python3 flipdot.py

Edit the CONFIG section below to match your setup.
"""

import serial
import numpy as np
import time
import sys
import logging

# ============================================================
# CONFIG — edit these values to match your setup
# ============================================================

PORT        = "/dev/cu.usbserial-BG01DCHX"
BAUD_RATE   = 57600
FRAME_DELAY = 0.1    # Seconds between frames — increase if panels miss frames

# Panel layout — 2D array of controller addresses.
# This tells flipPyDot how your controllers are arranged.
# Rows = top to bottom, columns = left to right.
# Each number = the DIP switch address on that controller board.
#
# Your 3x3 grid of 14x28 physical panels = 3 cols x 6 controller rows.
# Each physical panel has a TOP and BOTTOM controller.
#
# Example (update addresses to match your actual DIP switches):
#   Physical panel (col1, row1) top    = address 0
#   Physical panel (col1, row1) bottom = address 1
#   Physical panel (col2, row1) top    = address 2  ... etc
#
LAYOUT = [
    [0,  2,  4],   # Controller row 1 — top half of physical row 1
    [1,  3,  5],   # Controller row 2 — bottom half of physical row 1
    [6,  8,  10],  # Controller row 3 — top half of physical row 2
    [7,  9,  11],  # Controller row 4 — bottom half of physical row 2
    [12, 14, 16],  # Controller row 5 — top half of physical row 3
    [13, 15, 17],  # Controller row 6 — bottom half of physical row 3
]

# ============================================================
# Setup
# ============================================================

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(message)s",
    handlers= [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("flipdot.log")
    ]
)
log = logging.getLogger(__name__)


def open_serial():
    log.info(f"Opening {PORT} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(
            port     = PORT,
            baudrate = BAUD_RATE,
            bytesize = serial.EIGHTBITS,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            timeout  = 1.0
        )
        log.info(f"Serial open: {ser.is_open}")
        return ser
    except serial.SerialException as e:
        log.error(f"Could not open port: {e}")
        log.error(f"Run 'ls /dev/cu.usb*' to find your port name")
        sys.exit(1)


def make_panel(layout=LAYOUT):
    """Create a flipPyDot Panel object from the layout."""
    from flippydot import Panel
    return Panel(layout, 28, 7, module_rotation=0, screen_preview=False)


def send_frame(ser, panel, frame):
    """
    Send a numpy frame to the display.
    frame: np.uint8 array of shape (total_height, total_width)
           0 = dot black, 1 = dot white
    """
    serial_data = panel.apply_frame(frame)
    # flipPyDot returns a numpy array of byte strings — extract and join
    if isinstance(serial_data, np.ndarray):
        raw = b"".join(serial_data.flatten().tolist())
    else:
        raw = bytes(serial_data)
    ser.write(raw)
    log.debug(f"Sent {len(raw)} bytes")


def get_dims(panel):
    return panel.get_total_width(), panel.get_total_height()


# ============================================================
# Display operations
# ============================================================

def fill(ser, panel):
    """All dots white."""
    w, h  = get_dims(panel)
    frame = np.ones((h, w), dtype=np.uint8)
    log.info(f"Fill all — {w}x{h}")
    send_frame(ser, panel, frame)

def clear(ser, panel):
    """All dots black."""
    w, h  = get_dims(panel)
    frame = np.zeros((h, w), dtype=np.uint8)
    log.info(f"Clear all — {w}x{h}")
    send_frame(ser, panel, frame)

def test_addresses(ser):
    """
    Light up one controller at a time.
    Use this to confirm your LAYOUT mapping is correct.
    Press Enter after each to advance.
    """
    log.info("=" * 50)
    log.info("ADDRESS TEST — lighting each controller one at a time")
    log.info("Watch which panel lights up and compare to your LAYOUT")
    log.info("=" * 50)

    from flippydot import Panel

    for row_idx, row in enumerate(LAYOUT):
        for col_idx, addr in enumerate(row):
            # Create a single-panel Panel just for this address
            single = Panel([[addr]], 28, 7, module_rotation=0, screen_preview=False)

            # Clear that single panel
            off = np.zeros((7, 28), dtype=np.uint8)
            data = single.apply_frame(off)
            raw  = b"".join(data.flatten().tolist()) if isinstance(data, np.ndarray) else bytes(data)
            ser.write(raw)
            time.sleep(0.1)

            # Light it up
            on   = np.ones((7, 28), dtype=np.uint8)
            data = single.apply_frame(on)
            raw  = b"".join(data.flatten().tolist()) if isinstance(data, np.ndarray) else bytes(data)
            ser.write(raw)

            log.info(f"  Address {addr:2d} — layout row {row_idx+1}, col {col_idx+1}")
            input("  Press Enter for next...")

            # Turn off
            data = single.apply_frame(off)
            raw  = b"".join(data.flatten().tolist()) if isinstance(data, np.ndarray) else bytes(data)
            ser.write(raw)
            time.sleep(0.1)

    log.info("Address test complete")


def flash(ser, panel, times=5):
    """Flash entire display on/off."""
    w, h = get_dims(panel)
    log.info(f"Flashing {times} times...")
    for i in range(times):
        send_frame(ser, panel, np.ones((h, w),  dtype=np.uint8))
        time.sleep(FRAME_DELAY)
        send_frame(ser, panel, np.zeros((h, w), dtype=np.uint8))
        time.sleep(FRAME_DELAY)
    log.info("Flash done")


def checkerboard(ser, panel, times=6):
    """Alternating checkerboard pattern."""
    w, h = get_dims(panel)
    log.info("Checkerboard...")
    for phase in range(times):
        frame = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                frame[y, x] = 1 if (x + y + phase) % 2 == 0 else 0
        send_frame(ser, panel, frame)
        time.sleep(FRAME_DELAY * 2)
    log.info("Done")


def wipe(ser, panel, direction='right'):
    """Wipe all dots on or off column by column."""
    w, h  = get_dims(panel)
    frame = np.zeros((h, w), dtype=np.uint8)
    log.info(f"Wipe {direction}...")
    cols  = range(w) if direction == 'right' else range(w - 1, -1, -1)
    for x in cols:
        frame[:, x] = 1
        send_frame(ser, panel, frame)
        time.sleep(FRAME_DELAY / 4)
    log.info("Done")


# ============================================================
# Interactive menu
# ============================================================

def menu():
    print("\n" + "=" * 40)
    print("  FLIPDOT CONTROLLER")
    print("=" * 40)
    print("  1. Fill all (white)")
    print("  2. Clear all (black)")
    print("  3. Flash")
    print("  4. Checkerboard")
    print("  5. Wipe right")
    print("  6. Test addresses (one at a time)")
    print("  7. Change layout and reconnect")
    print("  0. Quit")
    print("=" * 40)
    return input("Choice: ").strip()


def main():
    ser   = open_serial()
    panel = make_panel()
    w, h  = get_dims(panel)
    log.info(f"Display: {w} wide x {h} tall ({len(LAYOUT)} controller rows x {len(LAYOUT[0])} cols)")
    log.info(f"Total controllers: {len(LAYOUT) * len(LAYOUT[0])}")

    while True:
        choice = menu()
        if choice == "1":
            fill(ser, panel)
        elif choice == "2":
            clear(ser, panel)
        elif choice == "3":
            times = input("How many flashes? [5]: ").strip() or "5"
            flash(ser, panel, int(times))
        elif choice == "4":
            checkerboard(ser, panel)
        elif choice == "5":
            wipe(ser, panel)
        elif choice == "6":
            test_addresses(ser)
        elif choice == "7":
            log.info("Edit LAYOUT in flipdot.py then restart the script")
        elif choice == "0":
            clear(ser, panel)
            ser.close()
            log.info("Goodbye")
            break
        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()
