"""
animations.py
-------------
Animation library for the flipdot display.
Each animation is a generator yielding (np.ndarray, delay_seconds).
All accept width/height as first two args plus named parameters.

Categories:
  GEOMETRIC  — spirals, rings, wipes, curtains, pinwheels
  PHYSICS    — gravity, bouncing balls, fireworks, ripples
  TEXT       — typewriter, clock, countdown
  CELLULAR   — Game of Life, spreading growth, static noise
  DATA       — bar charts, oscilloscopes, spectrum
"""

import numpy as np
import math
import random
import time
from datetime import datetime

# ── Helpers ───────────────────────────────────────────────────────

def empty(w, h): return np.zeros((h, w), dtype=np.uint8)
def full(w, h):  return np.ones((h, w),  dtype=np.uint8)

def circle_mask(w, h, cx, cy, r):
    """Boolean mask of all dots within radius r of (cx, cy)."""
    y, x = np.ogrid[:h, :w]
    return ((x - cx)**2 + (y - cy)**2) <= r**2

# ── GEOMETRIC ─────────────────────────────────────────────────────

def anim_wipe_right(w=84, h=42, delay=0.015, **kw):
    """Sweep dots ON left to right."""
    f = empty(w, h)
    for x in range(w):
        f[:, x] = 1
        yield f.copy(), delay

def anim_wipe_left(w=84, h=42, delay=0.015, **kw):
    f = full(w, h)
    for x in range(w-1, -1, -1):
        f[:, x] = 0
        yield f.copy(), delay

def anim_wipe_down(w=84, h=42, delay=0.04, **kw):
    f = empty(w, h)
    for y in range(h):
        f[y, :] = 1
        yield f.copy(), delay

def anim_wipe_up(w=84, h=42, delay=0.04, **kw):
    f = full(w, h)
    for y in range(h-1, -1, -1):
        f[y, :] = 0
        yield f.copy(), delay

def anim_curtain_open(w=84, h=42, delay=0.03, **kw):
    """Wipe from center outward (left and right simultaneously)."""
    f = full(w, h)
    cx = w // 2
    for i in range(cx + 1):
        f[:, cx - i] = 0
        if cx + i < w: f[:, cx + i] = 0
        yield f.copy(), delay

def anim_curtain_close(w=84, h=42, delay=0.03, **kw):
    f = empty(w, h)
    cx = w // 2
    for i in range(cx + 1):
        f[:, cx - i] = 1
        if cx + i < w: f[:, cx + i] = 1
        yield f.copy(), delay

def anim_blinds(w=84, h=42, slats=6, delay=0.06, **kw):
    """Venetian blind effect — horizontal slats close one by one."""
    slat_h = max(1, h // slats)
    f = empty(w, h)
    for s in range(slats):
        for row in range(s * slat_h, min((s+1) * slat_h, h)):
            f[row, :] = 1
        yield f.copy(), delay
    # then open
    for s in range(slats):
        for row in range(s * slat_h, min((s+1) * slat_h, h)):
            f[row, :] = 0
        yield f.copy(), delay

def anim_expanding_rings(w=84, h=42, delay=0.06, thickness=2, **kw):
    """Concentric rings expanding from center."""
    cx, cy = w // 2, h // 2
    max_r  = int(math.sqrt(cx**2 + cy**2)) + 2
    for r in range(0, max_r, thickness):
        f = empty(w, h)
        for dr in range(thickness):
            mask = circle_mask(w, h, cx, cy, r + dr)
            inner = circle_mask(w, h, cx, cy, max(0, r + dr - thickness))
            f[mask & ~inner] = 1
        yield f, delay

def anim_spiral_fill(w=84, h=42, delay=0.008, **kw):
    """Fill dots in a spiral pattern from center."""
    cx, cy = w // 2, h // 2
    # Generate spiral coordinates
    coords = []
    for r in range(max(cx, cy, w - cx, h - cy) + 1):
        for angle_step in range(360 * max(1, r)):
            angle = angle_step / max(1, r) * (math.pi / 180) if r > 0 else 0
            x = int(cx + r * math.cos(angle))
            y = int(cy + r * math.sin(angle))
            if 0 <= x < w and 0 <= y < h:
                if (x, y) not in set(coords):
                    coords.append((x, y))
    # Deduplicate preserving order
    seen = set()
    unique = []
    for c in coords:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    f = empty(w, h)
    batch = max(1, len(unique) // 200)
    for i, (x, y) in enumerate(unique):
        f[y, x] = 1
        if i % batch == 0:
            yield f.copy(), delay

def anim_diagonal_wipe(w=84, h=42, delay=0.02, direction="tl", **kw):
    """Diagonal wipe: tl=top-left, tr=top-right."""
    f = empty(w, h)
    steps = w + h
    for d in range(steps):
        for y in range(h):
            if direction == "tl":
                x = d - y
            else:
                x = d - (h - 1 - y)
            if 0 <= x < w:
                f[y, x] = 1
        yield f.copy(), delay

def anim_checkerboard(w=84, h=42, cycles=8, delay=0.18, **kw):
    for phase in range(cycles):
        f = np.fromfunction(lambda y, x: (x+y+phase)%2, (h,w), dtype=int).astype(np.uint8)
        yield f, delay

def anim_flash(w=84, h=42, times=6, delay=0.12, **kw):
    for _ in range(times):
        yield full(w, h), delay
        yield empty(w, h), delay

def anim_pinwheel(w=84, h=42, frames=48, delay=0.05, blades=4, **kw):
    cx, cy = w/2, h/2
    for n in range(frames):
        f = empty(w, h)
        offset = n * (2*math.pi / frames)
        for y in range(h):
            for x in range(w):
                dx, dy = x - cx, y - cy
                angle  = math.atan2(dy, dx)
                blade  = (angle + offset) % (2*math.pi / blades)
                if blade < math.pi / blades:
                    f[y, x] = 1
        yield f, delay

# ── PHYSICS ───────────────────────────────────────────────────────

def anim_gravity(w=84, h=42, particles=60, delay=0.05, **kw):
    """Dots fall from the top and pile up at the bottom."""
    grid = np.zeros((h, w), dtype=np.uint8)
    drops = [(random.randint(0, w-1), 0) for _ in range(particles)]
    active = list(drops)
    settled = 0
    while active or settled < particles:
        # Move each active drop down
        next_active = []
        for (x, y) in active:
            ny = y + 1
            if ny >= h or grid[ny, x] == 1:
                grid[y, x] = 1
                settled += 1
            else:
                grid[y, x] = 0
                grid[ny, x] = 1
                next_active.append((x, ny))
        active = next_active
        # Spawn new drops from top
        if len(active) < 5 and settled < particles:
            active.append((random.randint(0, w-1), 0))
        yield grid.copy(), delay
    yield grid.copy(), 1.0

def anim_bounce_balls(w=84, h=42, balls=4, frames=200, delay=0.04, **kw):
    """Multiple balls bouncing with gravity."""
    state = []
    for _ in range(balls):
        state.append({
            "x": random.uniform(2, w-2), "y": random.uniform(0, h//2),
            "vx": random.uniform(-1.5, 1.5), "vy": random.uniform(-1, 1),
        })
    gravity = 0.3
    damping = 0.75
    for _ in range(frames):
        f = empty(w, h)
        for b in state:
            b["vy"] += gravity
            b["x"]  += b["vx"]
            b["y"]  += b["vy"]
            if b["x"] <= 1 or b["x"] >= w-2:
                b["vx"] *= -damping
                b["x"]   = max(1, min(w-2, b["x"]))
            if b["y"] >= h-2:
                b["vy"] *= -damping
                b["y"]   = h-2
                b["vx"] *= 0.98
            if b["y"] <= 0:
                b["vy"] *= -1
                b["y"]   = 0
            # Draw 3x3 ball
            xi, yi = int(b["x"]), int(b["y"])
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx, ny = xi+dx, yi+dy
                    if 0 <= nx < w and 0 <= ny < h:
                        f[ny, nx] = 1
        yield f, delay

def anim_fireworks(w=84, h=42, bursts=5, delay=0.05, **kw):
    """Fireworks launch, explode, and fade."""
    for _ in range(bursts):
        # Launch
        cx = random.randint(w//4, 3*w//4)
        launch_y = h - 1
        peak_y   = random.randint(5, h//2)
        for y in range(launch_y, peak_y, -1):
            f = empty(w, h)
            f[y, cx] = 1
            if y + 1 < h: f[y+1, cx] = 1
            yield f, delay * 0.5

        # Explode — expanding ring of particles
        num_p = random.randint(16, 24)
        particles = []
        for i in range(num_p):
            angle = i * (2*math.pi / num_p)
            speed = random.uniform(1.5, 3.5)
            particles.append({
                "x": float(cx), "y": float(peak_y),
                "vx": math.cos(angle)*speed, "vy": math.sin(angle)*speed*0.6,
                "life": random.randint(8, 14)
            })
        for tick in range(20):
            f = empty(w, h)
            for p in particles:
                if p["life"] <= 0: continue
                p["x"] += p["vx"]
                p["y"] += p["vy"]
                p["vy"] += 0.15
                p["life"] -= 1
                xi, yi = int(p["x"]), int(p["y"])
                if 0 <= xi < w and 0 <= yi < h:
                    f[yi, xi] = 1
            yield f, delay
        yield empty(w, h), delay * 2

def anim_ripple(w=84, h=42, ripples=3, delay=0.06, **kw):
    """Expanding ripple rings from random points."""
    for _ in range(ripples):
        cx = random.randint(w//4, 3*w//4)
        cy = random.randint(h//4, 3*h//4)
        max_r = int(math.sqrt((max(cx, w-cx))**2 + (max(cy, h-cy))**2)) + 2
        for r in range(0, max_r, 2):
            f = empty(w, h)
            for ring_r in [r, r-1]:
                if ring_r < 0: continue
                mask  = circle_mask(w, h, cx, cy, ring_r)
                inner = circle_mask(w, h, cx, cy, max(0, ring_r-2))
                f[mask & ~inner] = 1
            yield f, delay

def anim_rain(w=84, h=42, frames=100, delay=0.06, density=0.3, **kw):
    drops = np.zeros(w, dtype=int)
    for _ in range(frames):
        f = empty(w, h)
        for x in range(w):
            if random.random() < density:
                drops[x] = (drops[x] + 1) % (h + 3)
            y = drops[x]
            if y < h:     f[y, x] = 1
            if y-1 >= 0:  f[y-1, x] = 1
        yield f, delay

# ── TEXT EFFECTS ──────────────────────────────────────────────────

def _get_font(size=14):
    from PIL import ImageFont
    import os
    fonts_dir = os.path.join(os.path.dirname(__file__), "..", "fonts")
    for fname in ["pixel.ttf", "mono.ttf"]:
        path = os.path.join(fonts_dir, fname)
        if os.path.isfile(path):
            try: return ImageFont.truetype(path, size)
            except: pass
    return ImageFont.load_default()

def _render_str(text, w, h, font_size=14, x=0, y=0):
    from PIL import Image, ImageDraw
    img  = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    draw.text((x, y), text, fill=0, font=_get_font(font_size))
    return (np.array(img, dtype=np.uint8) < 128).astype(np.uint8)

def anim_typewriter(w=84, h=42, text="HELLO WORLD", font_size=14,
                    char_delay=0.15, hold=2.0, **kw):
    """Type each character one at a time."""
    for i in range(1, len(text) + 1):
        f = _render_str(text[:i], w, h, font_size)
        yield f, char_delay
    yield f, hold

def anim_clock(w=84, h=42, duration=30, delay=1.0, font_size=21, **kw):
    """Live clock — updates every second for `duration` seconds."""
    start = time.time()
    while time.time() - start < duration:
        now  = datetime.now().strftime("%H:%M:%S")
        f    = _render_str(now, w, h, font_size, x=2, y=(h - font_size) // 2)
        yield f, delay

def anim_countdown(w=84, h=42, start_n=10, font_size=28, delay=1.0, **kw):
    """Countdown from start_n to 0."""
    for n in range(start_n, -1, -1):
        txt = str(n)
        # Center text
        f   = _render_str(txt, w, h, font_size,
                          x=max(0, (w - font_size * len(txt) // 2) // 2),
                          y=(h - font_size) // 2)
        yield f, delay
    yield empty(w, h), 0.5

def anim_scroll_text(bitmap: np.ndarray, dw: int = 84, delay: float = 0.04, **kw):
    bw = bitmap.shape[1]
    for offset in range(bw - dw + 1):
        yield bitmap[:, offset:offset+dw].copy(), delay

# ── CELLULAR AUTOMATA ─────────────────────────────────────────────

def anim_game_of_life(w=84, h=42, frames=100, delay=0.1,
                      density=0.35, **kw):
    """Conway's Game of Life."""
    grid = (np.random.rand(h, w) < density).astype(np.uint8)
    for _ in range(frames):
        yield grid.copy(), delay
        # Count neighbours (toroidal)
        nbrs = sum(
            np.roll(np.roll(grid, dy, 0), dx, 1)
            for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if (dy != 0 or dx != 0)
        )
        grid = ((nbrs == 3) | ((grid == 1) & (nbrs == 2))).astype(np.uint8)

def anim_spreading(w=84, h=42, seeds=8, delay=0.05, **kw):
    """Random seeds spread outward like lichen."""
    grid = empty(w, h)
    # Plant seeds
    for _ in range(seeds):
        x, y = random.randint(0, w-1), random.randint(0, h-1)
        grid[y, x] = 1
    frontier = list(zip(*np.where(grid == 1)))
    for _ in range(w * h):
        if not frontier: break
        next_f = []
        random.shuffle(frontier)
        for (y, x) in frontier[:max(1, len(frontier)//2)]:
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                ny, nx = y+dy, x+dx
                if 0 <= nx < w and 0 <= ny < h and grid[ny, nx] == 0:
                    if random.random() < 0.4:
                        grid[ny, nx] = 1
                        next_f.append((ny, nx))
        frontier = list(zip(*np.where(grid == 1))) if not next_f else next_f
        yield grid.copy(), delay

def anim_static_noise(w=84, h=42, frames=30, delay=0.08,
                      density=0.5, **kw):
    for _ in range(frames):
        yield (np.random.rand(h, w) < density).astype(np.uint8), delay

def anim_cellular_automata(w=84, h=42, frames=80, delay=0.08,
                            birth="3", survive="23", density=0.4, **kw):
    """Generalised Life rules. birth/survive are digit strings."""
    birth_s   = set(int(c) for c in str(birth))
    survive_s = set(int(c) for c in str(survive))
    grid = (np.random.rand(h, w) < density).astype(np.uint8)
    for _ in range(frames):
        yield grid.copy(), delay
        nbrs = sum(np.roll(np.roll(grid, dy, 0), dx, 1)
                   for dy in (-1,0,1) for dx in (-1,0,1) if (dy,dx) != (0,0))
        born    = (grid == 0) & np.isin(nbrs, list(birth_s))
        survives= (grid == 1) & np.isin(nbrs, list(survive_s))
        grid    = (born | survives).astype(np.uint8)

# ── DATA / AUDIO REACTIVE ─────────────────────────────────────────

def anim_bar_chart(w=84, h=42, frames=60, delay=0.08,
                   bars=14, **kw):
    """Animated bar chart with random data that smoothly updates."""
    heights = [random.randint(2, h) for _ in range(bars)]
    targets = list(heights)
    bar_w   = max(1, w // bars)
    for _ in range(frames):
        f = empty(w, h)
        for i, ht in enumerate(heights):
            x0 = i * bar_w
            x1 = min(x0 + bar_w - 1, w)
            f[h-int(ht):h, x0:x1] = 1
        yield f, delay
        # Smoothly move toward targets
        for i in range(bars):
            diff = targets[i] - heights[i]
            heights[i] += diff * 0.3
            if abs(diff) < 0.5:
                targets[i] = random.randint(2, h)

def anim_oscilloscope(w=84, h=42, frames=80, delay=0.05,
                      freq=2.0, amp=0.8, **kw):
    """Multi-wave oscilloscope display."""
    for n in range(frames):
        f  = empty(w, h)
        cy = h // 2
        for x in range(w):
            t  = x / w * 2 * math.pi * freq
            # Lissajous-style compound wave
            y1 = cy + int(cy * amp * 0.6 * math.sin(t + n * 0.1))
            y2 = cy + int(cy * amp * 0.3 * math.sin(t * 2 - n * 0.15))
            y  = max(0, min(h-1, y1 + y2 - cy))
            f[y, x] = 1
            # Draw trace line between adjacent points
            if x > 0:
                pt  = x - 1
                t2  = pt / w * 2 * math.pi * freq
                py1 = cy + int(cy * amp * 0.6 * math.sin(t2 + n * 0.1))
                py2 = cy + int(cy * amp * 0.3 * math.sin(t2 * 2 - n * 0.15))
                py  = max(0, min(h-1, py1 + py2 - cy))
                for iy in range(min(y, py), max(y, py) + 1):
                    f[iy, pt] = 1
        yield f, delay

def anim_spectrum(w=84, h=42, frames=80, delay=0.06, **kw):
    """Simulated audio spectrum analyser with peak hold."""
    bands  = w
    levels = np.zeros(bands)
    peaks  = np.zeros(bands)
    for _ in range(frames):
        f = empty(w, h)
        # Random spectrum with bass-heavy distribution
        targets = np.array([
            random.gauss(0.4, 0.25) * math.exp(-i / (bands * 0.4))
            + random.gauss(0.2, 0.1)
            for i in range(bands)
        ])
        targets = np.clip(targets, 0, 1)
        levels  = levels * 0.6 + targets * 0.4
        peaks   = np.maximum(peaks * 0.97, levels)
        for x in range(bands):
            bar_h = int(levels[x] * h)
            if bar_h > 0:
                f[h-bar_h:h, x] = 1
            pk = int(peaks[x] * h)
            if 0 < pk < h:
                f[h-pk-1, x] = 1
        yield f, delay

def anim_sine_wave(w=84, h=42, frames=80, delay=0.04,
                   freq=2.0, **kw):
    for n in range(frames):
        f = empty(w, h)
        for x in range(w):
            y = int((math.sin((x/w)*2*math.pi*freq + n*0.15)+1)/2*(h-1))
            f[min(y, h-1), x] = 1
            if y+1 < h: f[y+1, x] = 1
        yield f, delay

# ── Registry ──────────────────────────────────────────────────────

ANIMATIONS = {
    # Geometric
    "wipe_right":      (anim_wipe_right,      "Wipe Right",       "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.1,"step":0.005,"default":0.015}]),
    "wipe_left":       (anim_wipe_left,       "Wipe Left",        "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.1,"step":0.005,"default":0.015}]),
    "wipe_down":       (anim_wipe_down,       "Wipe Down",        "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.15,"step":0.01,"default":0.04}]),
    "wipe_up":         (anim_wipe_up,         "Wipe Up",          "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.15,"step":0.01,"default":0.04}]),
    "curtain_open":    (anim_curtain_open,    "Curtain Open",     "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.03}]),
    "curtain_close":   (anim_curtain_close,   "Curtain Close",    "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.03}]),
    "blinds":          (anim_blinds,          "Blinds",           "geometric",
                        [{"id":"slats","label":"Slats","type":"range","min":2,"max":12,"step":1,"default":6},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.2,"step":0.02,"default":0.06}]),
    "expanding_rings": (anim_expanding_rings, "Expanding Rings",  "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.2,"step":0.02,"default":0.06},
                         {"id":"thickness","label":"Thickness","type":"range","min":1,"max":5,"step":1,"default":2}]),
    "diagonal_wipe":   (anim_diagonal_wipe,   "Diagonal Wipe",    "geometric",
                        [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.08,"step":0.005,"default":0.02}]),
    "checkerboard":    (anim_checkerboard,    "Checkerboard",     "geometric",
                        [{"id":"cycles","label":"Cycles","type":"range","min":2,"max":20,"step":1,"default":8},
                         {"id":"delay","label":"Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.18}]),
    "flash":           (anim_flash,           "Flash",            "geometric",
                        [{"id":"times","label":"Times","type":"range","min":1,"max":20,"step":1,"default":6},
                         {"id":"delay","label":"Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.12}]),
    "pinwheel":        (anim_pinwheel,        "Pinwheel",         "geometric",
                        [{"id":"frames","label":"Frames","type":"range","min":12,"max":96,"step":4,"default":48},
                         {"id":"blades","label":"Blades","type":"range","min":2,"max":8,"step":1,"default":4},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.05}]),
    # Physics
    "gravity":         (anim_gravity,         "Gravity",          "physics",
                        [{"id":"particles","label":"Particles","type":"range","min":10,"max":120,"step":5,"default":60},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.05}]),
    "bounce_balls":    (anim_bounce_balls,    "Bounce Balls",     "physics",
                        [{"id":"balls","label":"Balls","type":"range","min":1,"max":10,"step":1,"default":4},
                         {"id":"frames","label":"Duration","type":"range","min":50,"max":400,"step":25,"default":200},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.12,"step":0.01,"default":0.04}]),
    "fireworks":       (anim_fireworks,       "Fireworks",        "physics",
                        [{"id":"bursts","label":"Bursts","type":"range","min":1,"max":10,"step":1,"default":5},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.05}]),
    "ripple":          (anim_ripple,          "Ripple",           "physics",
                        [{"id":"ripples","label":"Ripples","type":"range","min":1,"max":6,"step":1,"default":3},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    "rain":            (anim_rain,            "Rain",             "physics",
                        [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":100},
                         {"id":"density","label":"Density","type":"range","min":0.05,"max":0.8,"step":0.05,"default":0.3},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    # Text
    "typewriter":      (anim_typewriter,      "Typewriter",       "text",
                        [{"id":"text","label":"Text","type":"text","default":"HELLO WORLD"},
                         {"id":"font_size","label":"Font Size","type":"range","min":7,"max":28,"step":1,"default":14},
                         {"id":"char_delay","label":"Char Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.15}]),
    "clock":           (anim_clock,           "Live Clock",       "text",
                        [{"id":"duration","label":"Duration (s)","type":"range","min":10,"max":120,"step":5,"default":30},
                         {"id":"font_size","label":"Font Size","type":"range","min":7,"max":21,"step":1,"default":21}]),
    "countdown":       (anim_countdown,       "Countdown",        "text",
                        [{"id":"start_n","label":"From","type":"range","min":3,"max":60,"step":1,"default":10},
                         {"id":"font_size","label":"Font Size","type":"range","min":14,"max":42,"step":1,"default":28}]),
    # Cellular
    "game_of_life":    (anim_game_of_life,    "Game of Life",     "cellular",
                        [{"id":"frames","label":"Generations","type":"range","min":20,"max":300,"step":10,"default":100},
                         {"id":"density","label":"Density","type":"range","min":0.1,"max":0.7,"step":0.05,"default":0.35},
                         {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.3,"step":0.02,"default":0.1}]),
    "spreading":       (anim_spreading,       "Spreading",        "cellular",
                        [{"id":"seeds","label":"Seeds","type":"range","min":1,"max":20,"step":1,"default":8},
                         {"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.05}]),
    "static_noise":    (anim_static_noise,    "Static Noise",     "cellular",
                        [{"id":"frames","label":"Frames","type":"range","min":10,"max":100,"step":5,"default":30},
                         {"id":"density","label":"Density","type":"range","min":0.1,"max":0.9,"step":0.05,"default":0.5},
                         {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.2,"step":0.01,"default":0.08}]),
    "cellular_auto":   (anim_cellular_automata,"Cellular Auto",   "cellular",
                        [{"id":"frames","label":"Generations","type":"range","min":20,"max":200,"step":10,"default":80},
                         {"id":"density","label":"Density","type":"range","min":0.1,"max":0.7,"step":0.05,"default":0.4},
                         {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.3,"step":0.02,"default":0.08}]),
    # Data
    "bar_chart":       (anim_bar_chart,       "Bar Chart",        "data",
                        [{"id":"bars","label":"Bars","type":"range","min":4,"max":28,"step":1,"default":14},
                         {"id":"frames","label":"Duration","type":"range","min":20,"max":120,"step":5,"default":60},
                         {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.2,"step":0.01,"default":0.08}]),
    "oscilloscope":    (anim_oscilloscope,    "Oscilloscope",     "data",
                        [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                         {"id":"freq","label":"Frequency","type":"range","min":0.5,"max":6.0,"step":0.5,"default":2.0},
                         {"id":"amp","label":"Amplitude","type":"range","min":0.2,"max":1.0,"step":0.1,"default":0.8},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.05}]),
    "spectrum":        (anim_spectrum,        "Spectrum",         "data",
                        [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    "sine_wave":       (anim_sine_wave,       "Sine Wave",        "data",
                        [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                         {"id":"freq","label":"Frequency","type":"range","min":0.5,"max":6.0,"step":0.5,"default":2.0},
                         {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.04}]),
}

CATEGORIES = {
    "geometric": "Geometric",
    "physics":   "Physics",
    "text":      "Text",
    "cellular":  "Cellular",
    "data":      "Data",
}

def list_animations():
    return [
        {"id": k, "name": v[1], "category": v[2], "params": v[3]}
        for k, v in ANIMATIONS.items()
    ]

def get_animation(name: str):
    entry = ANIMATIONS.get(name)
    return entry[0] if entry else None
