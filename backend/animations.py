"""
animations.py — Flipdot Animation Library
28 animations across 5 categories.
Each is a generator yielding (numpy_array, delay_seconds).
"""

import numpy as np
import math, random, time
from datetime import datetime

def empty(w, h): return np.zeros((h, w), dtype=np.uint8)
def full(w, h):  return np.ones((h, w),  dtype=np.uint8)

def circle_mask(w, h, cx, cy, r):
    y, x = np.ogrid[:h, :w]
    return ((x-cx)**2 + (y-cy)**2) <= r**2

# ── GEOMETRIC ─────────────────────────────────────────────────────

def anim_wipe_right(w=84, h=42, delay=0.015, **kw):
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
    f = full(w, h)
    cx = w // 2
    for i in range(cx + 1):
        if cx - i >= 0: f[:, cx-i] = 0
        if cx + i < w:  f[:, cx+i] = 0
        yield f.copy(), delay

def anim_curtain_close(w=84, h=42, delay=0.03, **kw):
    f = empty(w, h)
    cx = w // 2
    for i in range(cx + 1):
        if cx - i >= 0: f[:, cx-i] = 1
        if cx + i < w:  f[:, cx+i] = 1
        yield f.copy(), delay

def anim_blinds(w=84, h=42, slats=6, delay=0.06, **kw):
    slat_h = max(1, h // int(slats))
    f = empty(w, h)
    for s in range(int(slats)):
        for row in range(s*slat_h, min((s+1)*slat_h, h)):
            f[row, :] = 1
        yield f.copy(), delay
    for s in range(int(slats)):
        for row in range(s*slat_h, min((s+1)*slat_h, h)):
            f[row, :] = 0
        yield f.copy(), delay

def anim_expanding_rings(w=84, h=42, delay=0.06, thickness=2, **kw):
    cx, cy = w//2, h//2
    max_r  = int(math.sqrt(cx**2 + cy**2)) + 2
    t = int(thickness)
    for r in range(0, max_r, max(1, t)):
        f = empty(w, h)
        for dr in range(t):
            mask  = circle_mask(w, h, cx, cy, r+dr)
            inner = circle_mask(w, h, cx, cy, max(0, r+dr-t))
            f[mask & ~inner] = 1
        yield f, delay

def anim_diagonal_wipe(w=84, h=42, delay=0.02, **kw):
    f = empty(w, h)
    for d in range(w + h):
        for y in range(h):
            x = d - y
            if 0 <= x < w:
                f[y, x] = 1
        yield f.copy(), delay

def anim_checkerboard(w=84, h=42, cycles=8, delay=0.18, **kw):
    for phase in range(int(cycles)):
        f = np.fromfunction(lambda y, x: (x+y+phase)%2, (h,w), dtype=int).astype(np.uint8)
        yield f, delay

def anim_flash(w=84, h=42, times=6, delay=0.12, **kw):
    for _ in range(int(times)):
        yield full(w, h), delay
        yield empty(w, h), delay

def anim_pinwheel(w=84, h=42, frames=48, delay=0.05, blades=4, **kw):
    cx, cy = w/2, h/2
    for n in range(int(frames)):
        f = empty(w, h)
        offset = n * (2*math.pi / int(frames))
        blade_arc = math.pi / int(blades)
        for y in range(h):
            for x in range(w):
                angle = math.atan2(y-cy, x-cx)
                if (angle + offset) % (2*math.pi/int(blades)) < blade_arc:
                    f[y, x] = 1
        yield f, delay

# ── PHYSICS ───────────────────────────────────────────────────────

def anim_gravity(w=84, h=42, particles=60, delay=0.05, **kw):
    grid   = empty(w, h)
    active = [(random.randint(0, w-1), 0) for _ in range(int(particles))]
    settled = 0
    total   = int(particles)
    while active or settled < total:
        nxt = []
        for (x, y) in active:
            ny = y + 1
            if ny >= h or grid[ny, x]:
                grid[y, x] = 1
                settled += 1
            else:
                grid[y, x] = 0
                grid[ny, x] = 1
                nxt.append((x, ny))
        active = nxt
        if len(active) < 5 and settled < total:
            active.append((random.randint(0, w-1), 0))
        yield grid.copy(), delay
    yield grid.copy(), 1.0

def anim_bounce_balls(w=84, h=42, balls=4, frames=200, delay=0.04, **kw):
    state = [{"x": float(random.randint(2,w-2)), "y": float(random.randint(0,h//2)),
              "vx": random.uniform(-1.5,1.5), "vy": random.uniform(-1,1)}
             for _ in range(int(balls))]
    for _ in range(int(frames)):
        f = empty(w, h)
        for b in state:
            b["vy"] += 0.3
            b["x"]  += b["vx"]; b["y"] += b["vy"]
            if b["x"] <= 1 or b["x"] >= w-2: b["vx"] *= -0.75; b["x"] = max(1, min(w-2, b["x"]))
            if b["y"] >= h-2: b["vy"] *= -0.75; b["y"] = h-2; b["vx"] *= 0.98
            if b["y"] <= 0:   b["vy"] *= -1;    b["y"] = 0
            xi, yi = int(b["x"]), int(b["y"])
            for dy in range(-1,2):
                for dx in range(-1,2):
                    nx2, ny2 = xi+dx, yi+dy
                    if 0 <= nx2 < w and 0 <= ny2 < h: f[ny2, nx2] = 1
        yield f, delay

def anim_fireworks(w=84, h=42, bursts=5, delay=0.05, **kw):
    for _ in range(int(bursts)):
        cx = random.randint(w//4, 3*w//4)
        peak_y = random.randint(5, h//2)
        for y in range(h-1, peak_y, -1):
            f = empty(w, h)
            f[y, cx] = 1
            if y+1 < h: f[y+1, cx] = 1
            yield f, delay*0.5
        num_p = random.randint(16, 24)
        parts = [{"x": float(cx), "y": float(peak_y),
                  "vx": math.cos(i*2*math.pi/num_p)*random.uniform(1.5,3.5),
                  "vy": math.sin(i*2*math.pi/num_p)*random.uniform(1.5,3.5)*0.6,
                  "life": random.randint(8,14)} for i in range(num_p)]
        for _ in range(20):
            f = empty(w, h)
            for p in parts:
                if p["life"] <= 0: continue
                p["x"] += p["vx"]; p["y"] += p["vy"]; p["vy"] += 0.15; p["life"] -= 1
                xi, yi = int(p["x"]), int(p["y"])
                if 0 <= xi < w and 0 <= yi < h: f[yi, xi] = 1
            yield f, delay
        yield empty(w, h), delay*2

def anim_ripple(w=84, h=42, ripples=3, delay=0.06, **kw):
    for _ in range(int(ripples)):
        cx = random.randint(w//4, 3*w//4)
        cy = random.randint(h//4, 3*h//4)
        max_r = int(math.sqrt(max(cx,w-cx)**2 + max(cy,h-cy)**2)) + 2
        for r in range(0, max_r, 2):
            f = empty(w, h)
            for rr in [r, r-1]:
                if rr < 0: continue
                mask  = circle_mask(w, h, cx, cy, rr)
                inner = circle_mask(w, h, cx, cy, max(0, rr-2))
                f[mask & ~inner] = 1
            yield f, delay

def anim_rain(w=84, h=42, frames=100, delay=0.06, density=0.3, **kw):
    drops = np.zeros(w, dtype=int)
    for _ in range(int(frames)):
        f = empty(w, h)
        for x in range(w):
            if random.random() < float(density):
                drops[x] = (drops[x]+1) % (h+3)
            y = drops[x]
            if y < h:    f[y, x] = 1
            if y-1 >= 0: f[y-1, x] = 1
        yield f, delay

# ── TEXT ──────────────────────────────────────────────────────────

def _font(size=14):
    from PIL import ImageFont
    import os
    fonts_dir = os.path.join(os.path.dirname(__file__), "..", "fonts")
    for fname in ["pixel.ttf","mono.ttf"]:
        p = os.path.join(fonts_dir, fname)
        if os.path.isfile(p):
            try: return ImageFont.truetype(p, int(size))
            except: pass
    return ImageFont.load_default()

def _render(text, w, h, size=14, x=0, y=0):
    from PIL import Image, ImageDraw
    img  = Image.new("L", (w, h), 255)
    ImageDraw.Draw(img).text((x, y), str(text), fill=0, font=_font(size))
    return (np.array(img) < 128).astype(np.uint8)

def anim_typewriter(w=84, h=42, text="HELLO WORLD", font_size=14, char_delay=0.15, hold=2.0, **kw):
    t = str(text)
    for i in range(1, len(t)+1):
        yield _render(t[:i], w, h, int(font_size)), float(char_delay)
    yield _render(t, w, h, int(font_size)), float(hold)

def anim_clock(w=84, h=42, duration=30, font_size=21, delay=1.0, **kw):
    start = time.time()
    while time.time() - start < float(duration):
        now = datetime.now().strftime("%H:%M:%S")
        sz  = int(font_size)
        yield _render(now, w, h, sz, x=2, y=(h-sz)//2), float(delay)

def anim_countdown(w=84, h=42, start_n=10, font_size=28, delay=1.0, **kw):
    for n in range(int(start_n), -1, -1):
        sz = int(font_size)
        yield _render(str(n), w, h, sz, x=max(0,(w-sz//2*(len(str(n))))//2), y=(h-sz)//2), float(delay)
    yield empty(w, h), 0.5

def anim_scroll_text(bitmap, dw=84, delay=0.04, **kw):
    bw = bitmap.shape[1]
    for offset in range(bw - dw + 1):
        yield bitmap[:, offset:offset+dw].copy(), delay

# ── CELLULAR ──────────────────────────────────────────────────────

def anim_game_of_life(w=84, h=42, frames=100, delay=0.1, density=0.35, **kw):
    grid = (np.random.rand(h, w) < float(density)).astype(np.uint8)
    for _ in range(int(frames)):
        yield grid.copy(), delay
        nbrs = sum(np.roll(np.roll(grid,dy,0),dx,1)
                   for dy in(-1,0,1) for dx in(-1,0,1) if (dy,dx)!=(0,0))
        grid = ((nbrs==3)|((grid==1)&(nbrs==2))).astype(np.uint8)

def anim_spreading(w=84, h=42, seeds=8, delay=0.05, **kw):
    grid = empty(w, h)
    for _ in range(int(seeds)):
        grid[random.randint(0,h-1), random.randint(0,w-1)] = 1
    for _ in range(w * h):
        pts = list(zip(*np.where(grid==1)))
        if not pts: break
        random.shuffle(pts)
        changed = False
        for (y, x) in pts[:max(1,len(pts)//4)]:
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                ny, nx = y+dy, x+dx
                if 0<=nx<w and 0<=ny<h and grid[ny,nx]==0 and random.random()<0.3:
                    grid[ny,nx] = 1
                    changed = True
        yield grid.copy(), delay
        if not changed: break

def anim_static_noise(w=84, h=42, frames=30, delay=0.08, density=0.5, **kw):
    for _ in range(int(frames)):
        yield (np.random.rand(h,w) < float(density)).astype(np.uint8), delay

def anim_cellular_auto(w=84, h=42, frames=80, delay=0.08, density=0.4, **kw):
    grid = (np.random.rand(h,w) < float(density)).astype(np.uint8)
    for _ in range(int(frames)):
        yield grid.copy(), delay
        nbrs = sum(np.roll(np.roll(grid,dy,0),dx,1)
                   for dy in(-1,0,1) for dx in(-1,0,1) if (dy,dx)!=(0,0))
        grid = ((nbrs==3)|((grid==1)&(nbrs==2))).astype(np.uint8)

# ── DATA ──────────────────────────────────────────────────────────

def anim_bar_chart(w=84, h=42, frames=60, delay=0.08, bars=14, **kw):
    b     = int(bars)
    hts   = [float(random.randint(2,h)) for _ in range(b)]
    tgts  = list(hts)
    bar_w = max(1, w // b)
    for _ in range(int(frames)):
        f = empty(w, h)
        for i, ht in enumerate(hts):
            x0 = i * bar_w
            x1 = min(x0 + bar_w - 1, w)
            f[h-int(ht):h, x0:x1] = 1
        yield f, delay
        for i in range(b):
            diff = tgts[i] - hts[i]
            hts[i] += diff * 0.3
            if abs(diff) < 0.5: tgts[i] = float(random.randint(2, h))

def anim_oscilloscope(w=84, h=42, frames=80, delay=0.05, freq=2.0, amp=0.8, **kw):
    cy = h // 2
    for n in range(int(frames)):
        f = empty(w, h)
        prev_y = None
        for x in range(w):
            t  = x/w * 2*math.pi * float(freq)
            y1 = cy + int(cy * float(amp) * 0.6 * math.sin(t + n*0.1))
            y2 = cy + int(cy * float(amp) * 0.3 * math.sin(t*2 - n*0.15))
            y  = max(0, min(h-1, y1+y2-cy))
            f[y, x] = 1
            if prev_y is not None:
                for iy in range(min(y, prev_y), max(y, prev_y)+1):
                    f[iy, max(0,x-1)] = 1
            prev_y = y
        yield f, delay

def anim_spectrum(w=84, h=42, frames=80, delay=0.06, **kw):
    levels = np.zeros(w)
    peaks  = np.zeros(w)
    for _ in range(int(frames)):
        f = empty(w, h)
        tgts = np.clip(
            np.array([random.gauss(0.4,0.25)*math.exp(-i/(w*0.4))+random.gauss(0.2,0.1)
                      for i in range(w)]), 0, 1)
        levels = levels*0.6 + tgts*0.4
        peaks  = np.maximum(peaks*0.97, levels)
        for x in range(w):
            bh = int(levels[x]*h)
            if bh > 0: f[h-bh:h, x] = 1
            pk = int(peaks[x]*h)
            if 0 < pk < h: f[h-pk-1, x] = 1
        yield f, delay

def anim_sine_wave(w=84, h=42, frames=80, delay=0.04, freq=2.0, **kw):
    for n in range(int(frames)):
        f = empty(w, h)
        for x in range(w):
            y = int((math.sin((x/w)*2*math.pi*float(freq)+n*0.15)+1)/2*(h-1))
            y = min(y, h-1)
            f[y, x] = 1
            if y+1 < h: f[y+1, x] = 1
        yield f, delay

# ── Registry ──────────────────────────────────────────────────────

ANIMATIONS = {
    "wipe_right":     (anim_wipe_right,    "Wipe Right",     "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.1,"step":0.005,"default":0.015}]),
    "wipe_left":      (anim_wipe_left,     "Wipe Left",      "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.1,"step":0.005,"default":0.015}]),
    "wipe_down":      (anim_wipe_down,     "Wipe Down",      "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.15,"step":0.01,"default":0.04}]),
    "wipe_up":        (anim_wipe_up,       "Wipe Up",        "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.15,"step":0.01,"default":0.04}]),
    "curtain_open":   (anim_curtain_open,  "Curtain Open",   "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.03}]),
    "curtain_close":  (anim_curtain_close, "Curtain Close",  "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.03}]),
    "blinds":         (anim_blinds,        "Blinds",         "geometric",
                       [{"id":"slats","label":"Slats","type":"range","min":2,"max":12,"step":1,"default":6},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.2,"step":0.02,"default":0.06}]),
    "expanding_rings":(anim_expanding_rings,"Expanding Rings","geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.2,"step":0.02,"default":0.06},
                        {"id":"thickness","label":"Thickness","type":"range","min":1,"max":5,"step":1,"default":2}]),
    "diagonal_wipe":  (anim_diagonal_wipe, "Diagonal Wipe",  "geometric",
                       [{"id":"delay","label":"Speed","type":"range","min":0.005,"max":0.08,"step":0.005,"default":0.02}]),
    "checkerboard":   (anim_checkerboard,  "Checkerboard",   "geometric",
                       [{"id":"cycles","label":"Cycles","type":"range","min":2,"max":20,"step":1,"default":8},
                        {"id":"delay","label":"Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.18}]),
    "flash":          (anim_flash,         "Flash",          "geometric",
                       [{"id":"times","label":"Times","type":"range","min":1,"max":20,"step":1,"default":6},
                        {"id":"delay","label":"Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.12}]),
    "pinwheel":       (anim_pinwheel,      "Pinwheel",       "geometric",
                       [{"id":"frames","label":"Frames","type":"range","min":12,"max":96,"step":4,"default":48},
                        {"id":"blades","label":"Blades","type":"range","min":2,"max":8,"step":1,"default":4},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.05}]),
    "gravity":        (anim_gravity,       "Gravity",        "physics",
                       [{"id":"particles","label":"Particles","type":"range","min":10,"max":120,"step":5,"default":60},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.05}]),
    "bounce_balls":   (anim_bounce_balls,  "Bounce Balls",   "physics",
                       [{"id":"balls","label":"Balls","type":"range","min":1,"max":10,"step":1,"default":4},
                        {"id":"frames","label":"Duration","type":"range","min":50,"max":400,"step":25,"default":200},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.12,"step":0.01,"default":0.04}]),
    "fireworks":      (anim_fireworks,     "Fireworks",      "physics",
                       [{"id":"bursts","label":"Bursts","type":"range","min":1,"max":10,"step":1,"default":5},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.05}]),
    "ripple":         (anim_ripple,        "Ripple",         "physics",
                       [{"id":"ripples","label":"Ripples","type":"range","min":1,"max":6,"step":1,"default":3},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    "rain":           (anim_rain,          "Rain",           "physics",
                       [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":100},
                        {"id":"density","label":"Density","type":"range","min":0.05,"max":0.8,"step":0.05,"default":0.3},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    "typewriter":     (anim_typewriter,    "Typewriter",     "text",
                       [{"id":"text","label":"Text","type":"text","default":"HELLO WORLD"},
                        {"id":"font_size","label":"Font Size","type":"range","min":7,"max":28,"step":1,"default":14},
                        {"id":"char_delay","label":"Char Speed","type":"range","min":0.05,"max":0.5,"step":0.05,"default":0.15}]),
    "clock":          (anim_clock,         "Live Clock",     "text",
                       [{"id":"duration","label":"Duration (s)","type":"range","min":10,"max":120,"step":5,"default":30},
                        {"id":"font_size","label":"Font Size","type":"range","min":7,"max":21,"step":1,"default":21}]),
    "countdown":      (anim_countdown,     "Countdown",      "text",
                       [{"id":"start_n","label":"From","type":"range","min":3,"max":60,"step":1,"default":10},
                        {"id":"font_size","label":"Font Size","type":"range","min":14,"max":42,"step":1,"default":28}]),
    "game_of_life":   (anim_game_of_life,  "Game of Life",   "cellular",
                       [{"id":"frames","label":"Generations","type":"range","min":20,"max":300,"step":10,"default":100},
                        {"id":"density","label":"Density","type":"range","min":0.1,"max":0.7,"step":0.05,"default":0.35},
                        {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.3,"step":0.02,"default":0.1}]),
    "spreading":      (anim_spreading,     "Spreading",      "cellular",
                       [{"id":"seeds","label":"Seeds","type":"range","min":1,"max":20,"step":1,"default":8},
                        {"id":"delay","label":"Speed","type":"range","min":0.01,"max":0.1,"step":0.01,"default":0.05}]),
    "static_noise":   (anim_static_noise,  "Static Noise",   "cellular",
                       [{"id":"frames","label":"Frames","type":"range","min":10,"max":100,"step":5,"default":30},
                        {"id":"density","label":"Density","type":"range","min":0.1,"max":0.9,"step":0.05,"default":0.5},
                        {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.2,"step":0.01,"default":0.08}]),
    "cellular_auto":  (anim_cellular_auto, "Cellular Auto",  "cellular",
                       [{"id":"frames","label":"Generations","type":"range","min":20,"max":200,"step":10,"default":80},
                        {"id":"density","label":"Density","type":"range","min":0.1,"max":0.7,"step":0.05,"default":0.4},
                        {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.3,"step":0.02,"default":0.08}]),
    "bar_chart":      (anim_bar_chart,     "Bar Chart",      "data",
                       [{"id":"bars","label":"Bars","type":"range","min":4,"max":28,"step":1,"default":14},
                        {"id":"frames","label":"Duration","type":"range","min":20,"max":120,"step":5,"default":60},
                        {"id":"delay","label":"Speed","type":"range","min":0.03,"max":0.2,"step":0.01,"default":0.08}]),
    "oscilloscope":   (anim_oscilloscope,  "Oscilloscope",   "data",
                       [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                        {"id":"freq","label":"Frequency","type":"range","min":0.5,"max":6.0,"step":0.5,"default":2.0},
                        {"id":"amp","label":"Amplitude","type":"range","min":0.2,"max":1.0,"step":0.1,"default":0.8},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.05}]),
    "spectrum":       (anim_spectrum,      "Spectrum",       "data",
                       [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.15,"step":0.01,"default":0.06}]),
    "sine_wave":      (anim_sine_wave,     "Sine Wave",      "data",
                       [{"id":"frames","label":"Duration","type":"range","min":30,"max":200,"step":10,"default":80},
                        {"id":"freq","label":"Frequency","type":"range","min":0.5,"max":6.0,"step":0.5,"default":2.0},
                        {"id":"delay","label":"Speed","type":"range","min":0.02,"max":0.1,"step":0.01,"default":0.04}]),
}

def list_animations():
    return [{"id":k,"name":v[1],"category":v[2],"params":v[3]} for k,v in ANIMATIONS.items()]

def get_animation(name):
    e = ANIMATIONS.get(name)
    return e[0] if e else None
