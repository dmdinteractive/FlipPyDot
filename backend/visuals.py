"""
visuals.py — Generative visuals that run forever.

Every one of these is endless: it keeps going until the playlist step's time
is up (or forever if you just send it). They're all written against time,
so "speed" stretches or squeezes time rather than skipping frames.

Shading on a 1-bit display: several of these compute a smooth brightness
field (0..1) and then ORDERED-DITHER it with a Bayer matrix. On flipdots that
reads as genuine grey tones from across a room, and — unlike random
dithering — a pixel only flips when the brightness under it actually
changes, so it doesn't buzz.
"""

import math
import time

import numpy as np

FPS = 20.0
DT = 1.0 / FPS

_B8 = np.array([[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
                [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
                [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
                [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]],
               dtype=float) / 64.0 + 1 / 128


def _bayer(w, h):
    return np.tile(_B8, (h // 8 + 1, w // 8 + 1))[:h, :w]


def dither(v):
    h, w = v.shape
    return (np.clip(v, 0, 1) > _bayer(w, h)).astype(np.uint8)


def _grid(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(float)
    return x, y


def _line(f, x0, y0, x1, y1):
    """Bresenham, clipped."""
    h, w = f.shape
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    for _ in range(dx - dy + 2):
        if 0 <= x0 < w and 0 <= y0 < h:
            f[y0, x0] = 1
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


# ── shaded fields ─────────────────────────────────────────────────
def plasma(w=84, h=42, speed=1.0, scale=1.0, **kw):
    x, y = _grid(w, h)
    s = 0.12 / float(scale)
    t = 0.0
    while True:
        v = (np.sin(x * s + t) + np.sin((y * s * 1.7) + t * 1.3)
             + np.sin((x + y) * s * 0.7 + t * 0.7)
             + np.sin(np.hypot(x - w / 2 + 20 * math.sin(t * 0.3), y - h / 2) * s * 1.4 - t))
        yield dither(v / 8 + 0.5), DT
        t += DT * float(speed) * 2


def tunnel(w=84, h=42, speed=1.0, rings=6, **kw):
    x, y = _grid(w, h)
    t = 0.0
    while True:
        cx = w / 2 + math.sin(t * 0.7) * w * 0.15
        cy = h / 2 + math.cos(t * 0.9) * h * 0.2
        d = np.hypot(x - cx, (y - cy) * 1.6) + 1
        a = np.arctan2(y - cy, x - cx)
        v = 0.5 + 0.5 * np.sin(float(rings) * 40 / d + t * 4) * np.cos(a * 4 + t)
        v *= np.clip(d / 12, 0, 1)
        yield dither(v), DT
        t += DT * float(speed)


def spiral(w=84, h=42, speed=1.0, arms=3, **kw):
    x, y = _grid(w, h)
    d = np.hypot(x - w / 2, (y - h / 2) * 1.0)
    a = np.arctan2(y - h / 2, x - w / 2)
    t = 0.0
    while True:
        v = 0.5 + 0.5 * np.sin(a * int(arms) + d * 0.35 - t * 3)
        yield dither(v), DT
        t += DT * float(speed)


def metaballs(w=84, h=42, balls=4, speed=1.0, outline=0, **kw):
    x, y = _grid(w, h)
    rng = np.random.default_rng(7)
    n = int(balls)
    ph = rng.uniform(0, 2 * math.pi, (n, 2))
    fr = rng.uniform(0.3, 0.9, (n, 2))
    r = rng.uniform(5, 9, n)
    t = 0.0
    while True:
        field = np.zeros((h, w))
        for i in range(n):
            bx = w / 2 + (w / 2 - 6) * math.sin(t * fr[i, 0] + ph[i, 0])
            by = h / 2 + (h / 2 - 4) * math.sin(t * fr[i, 1] + ph[i, 1])
            field += r[i] ** 2 / ((x - bx) ** 2 + (y - by) ** 2 + 1)
        f = (field > 1.0).astype(np.uint8)
        if int(outline):
            inner = (field > 1.6).astype(np.uint8)
            f = f & (1 - inner)
        yield f, DT
        t += DT * float(speed)


def ripple_pool(w=84, h=42, drops=1.0, speed=1.0, **kw):
    """The 2-D wave equation. Raindrops land and the rings interfere."""
    a = np.zeros((h, w))
    b = np.zeros((h, w))
    rng = np.random.default_rng()
    while True:
        for _ in range(max(1, int(round(float(speed) * 2)))):
            if rng.random() < 0.06 * float(drops):
                yy, xx = rng.integers(2, h - 2), rng.integers(2, w - 2)
                a[yy - 1:yy + 2, xx - 1:xx + 2] += 6
            lap = (np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 2 - b
            b, a = a, lap * 0.97
        yield dither(0.5 + a * 0.25), DT


# ── particles and geometry ────────────────────────────────────────
def starfield(w=84, h=42, stars=90, speed=1.0, **kw):
    rng = np.random.default_rng()
    n = int(stars)
    p = np.stack([rng.uniform(-1, 1, n), rng.uniform(-1, 1, n), rng.uniform(0.1, 1, n)], 1)
    while True:
        f = np.zeros((h, w), np.uint8)
        prev = p.copy()
        p[:, 2] -= DT * 0.5 * float(speed)
        dead = p[:, 2] <= 0.05
        p[dead] = np.stack([rng.uniform(-1, 1, dead.sum()), rng.uniform(-1, 1, dead.sum()),
                            np.ones(dead.sum())], 1)
        prev[dead] = p[dead]
        for (x0, y0, z0), (x1, y1, z1) in zip(prev, p):
            sx0, sy0 = w / 2 + x0 / z0 * w * 0.4, h / 2 + y0 / z0 * h * 0.4
            sx1, sy1 = w / 2 + x1 / z1 * w * 0.4, h / 2 + y1 / z1 * h * 0.4
            if z1 < 0.4:
                _line(f, sx0, sy0, sx1, sy1)       # near stars streak
            elif 0 <= int(sx1) < w and 0 <= int(sy1) < h:
                f[int(sy1), int(sx1)] = 1
        yield f, DT


_SHAPES = {
    "cube": ([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
             [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7),
              (4, 5), (4, 6), (5, 7), (6, 7)]),
    "pyramid": ([(-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1), (0, -1.2, 0)],
                [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]),
    "octahedron": ([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
                   [(a, b) for a in (0, 1) for b in (2, 3, 4, 5)] + [(2, 4), (4, 3), (3, 5), (5, 2)]),
}


def wireframe(w=84, h=42, shape="cube", speed=1.0, size=1.0, **kw):
    verts, edges = _SHAPES.get(shape, _SHAPES["cube"])
    v = np.array(verts, float)
    t = 0.0
    while True:
        a, b = t * 0.9, t * 0.6
        ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
        p = v @ ry.T @ rx.T
        z = p[:, 2] + 4
        k = h * 1.5 * float(size)
        sx = w / 2 + p[:, 0] / z * k
        sy = h / 2 + p[:, 1] / z * k
        f = np.zeros((h, w), np.uint8)
        for i, j in edges:
            _line(f, sx[i], sy[i], sx[j], sy[j])
        yield f, DT
        t += DT * float(speed)


def lissajous(w=84, h=42, speed=1.0, trail=120, **kw):
    t = 0.0
    while True:
        f = np.zeros((h, w), np.uint8)
        a, b = 3, 2
        d = t * 0.4
        s = np.linspace(0, 2 * math.pi, int(trail) * 3)
        xs = w / 2 + (w / 2 - 2) * np.sin(a * s + d)
        ys = h / 2 + (h / 2 - 2) * np.sin(b * s)
        for i in range(len(s) - 1):
            _line(f, xs[i], ys[i], xs[i + 1], ys[i + 1])
        yield f, DT
        t += DT * float(speed)


def boids(w=84, h=42, birds=24, speed=1.0, **kw):
    rng = np.random.default_rng()
    n = int(birds)
    p = rng.uniform([0, 0], [w, h], (n, 2))
    v = rng.uniform(-1, 1, (n, 2)) * 10
    while True:
        d = p[:, None, :] - p[None, :, :]
        d -= np.round(d / [w, h]) * [w, h]            # wrap-around distances
        dist = np.hypot(d[..., 0], d[..., 1]) + np.eye(n) * 1e3
        near = dist < 12
        cnt = near.sum(1, keepdims=True).clip(1)
        coh = -(d * near[..., None]).sum(1) / cnt
        ali = (v[None, :, :] * near[..., None]).sum(1) / cnt - v
        sep = (d / dist[..., None] ** 2 * (dist < 4)[..., None]).sum(1)
        v += (coh * 0.4 + ali * 0.3 + sep * 30) * DT * float(speed)
        sp = np.hypot(v[:, 0], v[:, 1]).clip(1e-3)[:, None]
        v = v / sp * np.clip(sp, 6, 16)
        p = (p + v * DT * float(speed)) % [w, h]
        f = np.zeros((h, w), np.uint8)
        for (x, y), (vx, vy) in zip(p, v):
            n_ = math.hypot(vx, vy) or 1
            _line(f, x, y, x - vx / n_ * 2, y - vy / n_ * 2)
        yield f, DT


def sand(w=84, h=42, speed=1.0, **kw):
    """Falling sand pouring from a wandering spout; drains when full."""
    g = np.zeros((h, w), np.uint8)
    rng = np.random.default_rng()
    t = 0.0
    draining = False
    while True:
        for _ in range(max(1, int(round(2 * float(speed))))):
            if not draining:
                sx = int(w / 2 + math.sin(t * 0.8) * w * 0.4)
                g[0, max(0, min(w - 1, sx))] = 1
            else:
                g[-1, :] = 0
            # move grains bottom-up so each falls at most once per tick
            for y in range(h - 2, -1, -1):
                row = np.nonzero(g[y])[0]
                if not len(row):
                    continue
                rng.shuffle(row)
                for x in row:
                    if not g[y + 1, x]:
                        g[y, x], g[y + 1, x] = 0, 1
                    else:
                        dirs = [-1, 1] if rng.random() < 0.5 else [1, -1]
                        for dx in dirs:
                            nx = x + dx
                            if 0 <= nx < w and not g[y + 1, nx]:
                                g[y, x], g[y + 1, nx] = 0, 1
                                break
            t += DT
        fill = g.mean()
        if fill > 0.55:
            draining = True
        elif draining and fill < 0.02:
            draining = False
        yield g.copy(), DT


def life(w=84, h=42, density=0.3, speed=1.0, **kw):
    """Conway's Life on a torus that reseeds itself when it goes stale."""
    rng = np.random.default_rng()
    g = (rng.random((h, w)) < float(density)).astype(np.uint8)
    seen = []
    while True:
        yield g.copy(), max(0.04, 0.12 / float(speed))
        nb = sum(np.roll(np.roll(g, dy, 0), dx, 1)
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
        g = ((nb == 3) | ((g == 1) & (nb == 2))).astype(np.uint8)
        key = g.tobytes()
        seen = (seen + [key])[-12:]
        if seen.count(key) > 2 or g.sum() < 6:
            g = (rng.random((h, w)) < float(density)).astype(np.uint8)
            seen = []


def matrix_rain(w=84, h=42, density=0.5, speed=1.0, **kw):
    rng = np.random.default_rng()
    heads = rng.uniform(-h, 0, w)
    vel = rng.uniform(8, 25, w)
    tail = rng.integers(4, 14, w)
    on = rng.random(w) < float(density)
    noise = rng.random((h * 3, w)) < 0.7
    t = 0.0
    while True:
        f = np.zeros((h, w), np.uint8)
        heads += vel * DT * float(speed)
        for x in range(w):
            if not on[x]:
                continue
            y1 = int(heads[x])
            y0 = y1 - int(tail[x])
            for y in range(max(0, y0), min(h, y1 + 1)):
                if y == y1 or noise[(y + int(t * 6)) % len(noise), x]:
                    f[y, x] = 1
            if y0 > h:
                heads[x] = rng.uniform(-h * 0.5, 0)
                vel[x] = rng.uniform(8, 25)
                on[x] = rng.random() < float(density)
        yield f, DT
        t += DT * float(speed)


def maze(w=84, h=42, speed=1.0, **kw):
    """Carve a maze with a visible depth-first search, solve it, repeat."""
    rng = np.random.default_rng()
    cw, ch = (w - 1) // 2, (h - 1) // 2
    while True:
        g = np.ones((h, w), np.uint8)
        stack = [(0, 0)]
        seen = {(0, 0)}
        g[1, 1] = 0
        steps = 0
        while stack:
            cx, cy = stack[-1]
            nbrs = [(cx + dx, cy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= cx + dx < cw and 0 <= cy + dy < ch and (cx + dx, cy + dy) not in seen]
            if nbrs:
                nx, ny = nbrs[rng.integers(len(nbrs))]
                g[1 + cy + ny, 1 + cx + nx] = 0
                g[1 + 2 * ny, 1 + 2 * nx] = 0
                seen.add((nx, ny))
                stack.append((nx, ny))
            else:
                stack.pop()
            steps += 1
            if steps % max(1, int(4 * float(speed))) == 0:
                yield g.copy(), DT
        yield g.copy(), 1.5
        # Solve by flood fill from top-left, then trace the route back.
        dist = -np.ones((h, w), int)
        dist[1, 1] = 0
        front = [(1, 1)]
        while front:
            nxt = []
            for x, y in front:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < w and 0 <= yy < h and g[yy, xx] == 0 and dist[yy, xx] < 0:
                        dist[yy, xx] = dist[y, x] + 1
                        nxt.append((xx, yy))
            front = nxt
        ex, ey = 2 * cw - 1, 2 * ch - 1
        path = [(ex, ey)]
        while path[-1] != (1, 1) and dist[ey, ex] > 0:
            x, y = path[-1]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and dist[yy, xx] == dist[y, x] - 1:
                    path.append((xx, yy))
                    break
            else:
                break
        out = 1 - g                     # draw the corridors, not the walls
        for i, (x, y) in enumerate(reversed(path)):
            out[y, x] = 0
            if i % max(1, int(3 * float(speed))) == 0:
                yield out.copy(), DT
        yield out.copy(), 3.0


def analog_clock(w=84, h=42, seconds=1, **kw):
    """Round clock face — the hands are drawn from the Mac mini's clock."""
    cx, cy = w / 2 - 0.5, h / 2 - 0.5
    r = min(w, h) / 2 - 1
    face = np.zeros((h, w), np.uint8)
    for k in range(60):
        a = k / 60 * 2 * math.pi
        inner = r - (3 if k % 5 == 0 else 0.8)
        _line(face, cx + math.sin(a) * inner, cy - math.cos(a) * inner,
              cx + math.sin(a) * r, cy - math.cos(a) * r)
    while True:
        lt = time.localtime()
        f = face.copy()
        hm = (lt.tm_hour % 12 + lt.tm_min / 60) / 12 * 2 * math.pi
        mm = (lt.tm_min + lt.tm_sec / 60) / 60 * 2 * math.pi
        _line(f, cx, cy, cx + math.sin(hm) * r * 0.5, cy - math.cos(hm) * r * 0.5)
        _line(f, cx, cy, cx + math.sin(mm) * r * 0.8, cy - math.cos(mm) * r * 0.8)
        if int(seconds):
            sm = lt.tm_sec / 60 * 2 * math.pi
            _line(f, cx, cy, cx + math.sin(sm) * r * 0.9, cy - math.cos(sm) * r * 0.9)
        yield f, 1.0 - (time.time() % 1.0)


def _p(id_, label, mn, mx, step, default):
    return {"id": id_, "label": label, "type": "range", "min": mn, "max": mx,
            "step": step, "default": default}


_SPEED = _p("speed", "Speed", 0.2, 4.0, 0.1, 1.0)

VISUALS = {
    "plasma":       (plasma,       "Plasma",        [_SPEED, _p("scale", "Scale", 0.4, 3.0, 0.1, 1.0)]),
    "tunnel":       (tunnel,       "Tunnel",        [_SPEED, _p("rings", "Rings", 2, 12, 1, 6)]),
    "spiral":       (spiral,       "Hypno Spiral",  [_SPEED, _p("arms", "Arms", 1, 8, 1, 3)]),
    "metaballs":    (metaballs,    "Metaballs",     [_SPEED, _p("balls", "Blobs", 2, 8, 1, 4),
                                                      _p("outline", "Outline only", 0, 1, 1, 0)]),
    "ripple_pool":  (ripple_pool,  "Rain on Water", [_SPEED, _p("drops", "Drops", 0.2, 4.0, 0.2, 1.0)]),
    "starfield":    (starfield,    "Warp Stars",    [_SPEED, _p("stars", "Stars", 20, 200, 10, 90)]),
    "wireframe":    (wireframe,    "3D Cube",       [_SPEED, _p("size", "Size", 0.5, 2.0, 0.1, 1.0)]),
    "wire_pyramid": (lambda w=84, h=42, **k: wireframe(w, h, shape="pyramid", **k),
                     "3D Pyramid", [_SPEED, _p("size", "Size", 0.5, 2.0, 0.1, 1.0)]),
    "wire_octa":    (lambda w=84, h=42, **k: wireframe(w, h, shape="octahedron", **k),
                     "3D Diamond", [_SPEED, _p("size", "Size", 0.5, 2.0, 0.1, 1.0)]),
    "lissajous":    (lissajous,    "Lissajous",     [_SPEED]),
    "boids":        (boids,        "Flocking Birds", [_SPEED, _p("birds", "Birds", 5, 60, 1, 24)]),
    "sand":         (sand,         "Falling Sand",  [_SPEED]),
    "life":         (life,         "Life (endless)", [_SPEED, _p("density", "Density", 0.1, 0.6, 0.05, 0.3)]),
    "matrix_rain":  (matrix_rain,  "Digital Rain",  [_SPEED, _p("density", "Density", 0.1, 1.0, 0.05, 0.5)]),
    "maze":         (maze,         "Maze Builder",  [_SPEED]),
    "analog_clock": (analog_clock, "Analog Clock",  [_p("seconds", "Second hand", 0, 1, 1, 1)]),
}
