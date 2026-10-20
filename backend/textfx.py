"""
textfx.py — Letter-by-letter text animation, and text over moving visuals.

A text spec can now have three phases:

    intro ──▶ idle ──▶ outro
    (arrive)  (while it's up)  (leave, timed to end exactly at the step's end)

    "intro": "type" | "decode" | "flap" | "drop" | "rise" | "dissolve"
             | "gather" | "wipe" | ""
    "idle":  "wave" | "sparkle" | "jitter" | "bounce" | "marquee" | ""
    "outro": "dissolve" | "explode" | "fall" | "wipe" | "type" | "flap" | ""
    "fx_speed": 1.0           (0.25 = slow and stately, 3 = snappy)

and an optional moving background:

    "bg": "plasma"            any animation id
    "bg_params": {...}
    "bg_blend": "outline" | "mask" | "xor" | "over"

Everything is a pure function of time and the spec, and every "random"
effect is seeded from the spec, so the browser preview and the panel show
exactly the same thing.

Why letters and not whole bitmaps: on a flipdot the sound IS the effect.
A split-flap "flap" intro makes each character clatter through the alphabet
on its own; a "decode" makes the dots chatter and then settle. Effects that
move whole blocks of text just sound like one big click.
"""

import math
import zlib

import numpy as np

import fonts as font_mod
from variables import substitute

INTROS = ["type", "decode", "flap", "drop", "rise", "dissolve", "gather", "wipe"]
IDLES  = ["wave", "sparkle", "jitter", "bounce", "marquee"]
OUTROS = ["dissolve", "explode", "fall", "wipe", "type", "flap"]
BLENDS = ["outline", "mask", "xor", "over"]

FLAP_SEQ = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NOISE_CH = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#$%&*+=?@"


def needs_fx(spec):
    return bool(spec.get("intro") or spec.get("idle") or spec.get("outro")
                or spec.get("bg"))


# ── easing ────────────────────────────────────────────────────────
def _clamp(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out(x):
    x = _clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x):
    x = _clamp(x)
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def ease_out_bounce(x):
    x = _clamp(x)
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + 0.75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + 0.9375
    x -= 2.625 / d
    return n * x * x + 0.984375


# ── layout: where every letter lives ──────────────────────────────
class Glyph:
    __slots__ = ("bmp", "x", "y", "ch", "i")

    def __init__(self, bmp, x, y, ch, i):
        self.bmp, self.x, self.y, self.ch, self.i = bmp, x, y, ch, i

    @property
    def w(self):
        return self.bmp.shape[1]

    @property
    def h(self):
        return self.bmp.shape[0]


def _bold(bmp):
    if bmp.size == 0:
        return bmp
    out = np.zeros((bmp.shape[0], bmp.shape[1] + 1), dtype=np.uint8)
    out[:, :-1] |= bmp
    out[:, 1:] |= bmp
    return out


def _line_glyphs(face, line, size, trk):
    """[(char, bitmap, x)] for one line, plus the line's (h, w)."""
    if face.kind == "bitmap":
        f = face._f
        scale = f.scale_for_height(size)
        cell = (f.gw + trk) * scale
        out = []
        for i, ch in enumerate(line):
            g = f.glyph(ch)
            if scale > 1:
                g = np.repeat(np.repeat(g, scale, 0), scale, 1)
            out.append((ch, g if ch != " " else g[:, :0], i * cell))
        w = max(0, len(line) * cell - trk * scale)
        return out, (f.gh * scale, w)

    # Proportional faces: render the whole line once (keeps the baseline and
    # kerning right), then cut it into letters at the measured advances.
    full = face.render(line, size, tracking=trk)
    if full.shape[1] == 0:
        return [], (full.shape[0], 0)
    out, prev = [], 0
    for i, ch in enumerate(line):
        end = face.render(line[:i + 1], size, tracking=trk).shape[1] if line[:i + 1].strip() else 0
        end = max(prev, min(full.shape[1], end))
        if ch != " ":
            out.append((ch, full[:, prev:end], prev))
        prev = end + (trk if ch != " " else 0)
    return out, full.shape


def layout_glyphs(spec, w, h, text=None):
    """Every visible letter with its home position on the panel."""
    from renderer import _aligned_xy
    text = substitute(str(spec.get("text", ""))) if text is None else text
    face = font_mod.get(spec.get("font", font_mod.DEFAULT_KEY))
    size = int(spec.get("size", 14))
    trk = int(spec.get("tracking", 1))
    lead = int(spec.get("leading", 1))
    bold = bool(spec.get("bold"))

    lines = []
    for ln in str(text).split("\n"):
        gl, (lh, lw) = _line_glyphs(face, ln, size, trk)
        if bold:
            gl = [(c, _bold(b), x) for c, b, x in gl]
            lw += 1 if lw else 0
        lines.append((gl, lh, lw))

    line_h = max((lh for _, lh, _ in lines), default=size)
    bw = max((lw for _, _, lw in lines), default=0)
    bh = len(lines) * (line_h + lead) - lead
    bx, by = _aligned_xy(bw, bh, w, h, spec.get("align", "center"),
                         spec.get("valign", "middle"),
                         int(spec.get("dx", 0)), int(spec.get("dy", 0)))
    glyphs, i = [], 0
    for li, (gl, lh, _) in enumerate(lines):
        for ch, bmp, x in gl:
            if bmp.size and bmp.any():
                glyphs.append(Glyph(bmp, bx + x, by + li * (line_h + lead), ch, i))
            i += 1
    return glyphs, (bx, by, bw, bh)


_glyph_cache = {}


def _char_bitmap(spec, ch):
    key = (spec.get("font"), int(spec.get("size", 14)), bool(spec.get("bold")), ch)
    b = _glyph_cache.get(key)
    if b is None:
        face = font_mod.get(spec.get("font", font_mod.DEFAULT_KEY))
        if face.kind == "bitmap":
            gl, _ = _line_glyphs(face, ch, int(spec.get("size", 14)), 0)
            b = gl[0][1] if gl else np.zeros((1, 0), np.uint8)
        else:
            b = face.render(ch, int(spec.get("size", 14)), tracking=0)
        if spec.get("bold"):
            b = _bold(b)
        if len(_glyph_cache) > 2000:
            _glyph_cache.clear()
        _glyph_cache[key] = b
    return b


# ── drawing helpers ───────────────────────────────────────────────
def blit(canvas, bmp, x, y):
    """OR a bitmap onto the canvas at (x, y), clipped."""
    H, W = canvas.shape
    bh, bw = bmp.shape
    x, y = int(round(x)), int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + bw), min(H, y + bh)
    if x1 <= x0 or y1 <= y0:
        return
    canvas[y0:y1, x0:x1] |= bmp[y0 - y:y1 - y, x0 - x:x1 - x]


def blit_in_box(canvas, bmp, g):
    """Draw a substitute character in glyph g's box (decode / flap)."""
    gh, gw = g.h, g.w
    bh, bw = bmp.shape
    ox = g.x + (gw - bw) // 2
    oy = g.y + (gh - bh)          # bottom-align: keeps the baseline steady
    blit(canvas, bmp, ox, oy)


def _seed(spec, *salt):
    s = f"{spec.get('text')}|{spec.get('intro')}|{spec.get('outro')}|{salt}"
    return zlib.crc32(s.encode())


def _rng(spec, *salt):
    return np.random.default_rng(_seed(spec, *salt))


def dilate(a, r=1):
    out = a.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                out |= np.roll(np.roll(a, dy, 0), dx, 1)
    return out


# ── the animator ──────────────────────────────────────────────────
class TextFX:
    def __init__(self, spec, w, h, duration=None):
        from renderer import MAX_FPS
        self.spec = spec
        self.w, self.h = w, h
        self.speed = max(0.1, float(spec.get("fx_speed", 1.0) or 1.0))
        self.intro = spec.get("intro") or ""
        motion = spec.get("motion") or "static"
        if not self.intro and motion.startswith("scroll_in_"):
            # Classic "slide in & stop", now able to pair with an outro.
            self.intro = "slide_" + motion[len("scroll_in_"):]
        self.idle = spec.get("idle") or ""
        self.outro = spec.get("outro") or ""
        self.dt = 1.0 / max(4.0, MAX_FPS)

        self.glyphs, self.box = layout_glyphs(spec, w, h)
        self.order = sorted(self.glyphs, key=lambda g: g.i)
        self.n = max(1, len(self.glyphs))
        self.final = np.zeros((h, w), dtype=np.uint8)
        for g in self.glyphs:
            blit(self.final, g.bmp, g.x, g.y)

        ys, xs = np.nonzero(self.final)
        self.px = np.stack([xs, ys], 1).astype(float) if len(xs) else np.zeros((0, 2))
        r = _rng(spec, "px")
        self.px_rand = r.random(len(self.px))
        self.px_from = np.stack([r.uniform(-w * 0.5, w * 1.5, len(self.px)),
                                 r.uniform(-h, h * 2, len(self.px))], 1)
        # Explode: every dot flies outward from the centre, plus a random kick.
        ang = r.uniform(0, 2 * math.pi, len(self.px))
        spd = r.uniform(15, 60, len(self.px))
        out = self.px - np.array([w / 2, h / 2])
        self.px_vel = np.stack([np.cos(ang) * spd + out[:, 0] * 0.8,
                                np.sin(ang) * spd - 25 + out[:, 1] * 0.8], 1)
        self.glyph_rand = _rng(spec, "g").random(len(self.glyphs) + 1)

        self.t_in = self._intro_len()
        self.t_out = self._outro_len() if duration else 0.0
        if duration:
            self.out_at = max(self.t_in, float(duration) - self.t_out)
        else:
            self.out_at = float("inf")

        blink = float(spec.get("blink", 0) or 0)
        self.blink = (blink, min(0.9, max(0.1, float(spec.get("blink_duty", 0.5) or 0.5)))) if blink > 0 else None

        self.bg = None
        if spec.get("bg"):
            from clip import Clip
            self.bg = Clip({"kind": "animation", "animation": spec["bg"],
                            "params": spec.get("bg_params") or {}}, w, h, loop=True)
        self.blend = spec.get("bg_blend") or "outline"

    # phase lengths -------------------------------------------------
    def _stagger(self):
        return 0.06 / self.speed

    def _intro_len(self):
        n, s = self.n, self.speed
        return {
            "type":     n * 0.09 / s + 0.3,
            "decode":   (0.5 + n * 0.05) / s,
            "flap":     (n * 0.03 + 12 * 0.07) / s,
            "drop":     n * self._stagger() + 0.9 / s,
            "rise":     n * self._stagger() + 0.6 / s,
            "dissolve": 1.2 / s,
            "gather":   1.4 / s,
            "wipe":     (self.w / 60.0) / s,
        }.get(self.intro, self._slide_len())

    def _slide_dist(self):
        bx, by, bw, bh = self.box
        d = self.intro[6:] if self.intro.startswith("slide_") else ""
        return {"left": self.w - bx, "right": bx + bw, "up": self.h - by,
                "down": by + bh}.get(d, 0)

    def _slide_len(self):
        if not self.intro.startswith("slide_"):
            return 0.0
        return self._slide_dist() / max(1.0, float(self.spec.get("speed", 30) or 30))

    def _outro_len(self):
        n, s = self.n, self.speed
        return {
            "dissolve": 1.0 / s,
            "explode":  1.6 / s,
            "fall":     n * 0.04 / s + 0.8 / s,
            "wipe":     (self.w / 60.0) / s,
            "type":     n * 0.05 / s + 0.1,
            "flap":     (n * 0.03 + 8 * 0.07) / s,
        }.get(self.outro, 0.0)

    # rendering ------------------------------------------------------
    def frame_at(self, t):
        if t < self.t_in:
            text = self._intro(t / max(1e-6, self.t_in), t)
        elif t >= self.out_at:
            text = self._outro(_clamp((t - self.out_at) / max(1e-6, self.t_out)),
                               t - self.out_at)
        else:
            text = self._idle(t - self.t_in)
            if self.blink:
                hz, duty = self.blink
                if ((t - self.t_in) * hz) % 1.0 >= duty:
                    text = np.zeros_like(text)
        return self._composite(text, t)

    def is_still(self, t):
        """True if nothing changes from t until the outro starts."""
        return (self.t_in <= t < self.out_at and not self.idle
                and not self.blink and self.bg is None)

    def frames(self):
        t = 0.0
        while True:
            if self.is_still(t):
                hold = self.out_at - t
                yield self.frame_at(t), (None if hold == float("inf") else hold)
                if hold == float("inf"):
                    return
                t = self.out_at
                continue
            if t >= self.out_at + self.t_out and self.t_out:
                yield np.zeros((self.h, self.w), np.uint8), None
                return
            yield self.frame_at(t), self.dt
            t += self.dt

    # composite with background visual -------------------------------
    def _composite(self, text, t):
        if self.bg is None:
            return text
        bg = self.bg.at(t)
        if bg is None:
            return text
        bg = bg.astype(np.uint8)
        if self.blend == "mask":
            return (bg & text).astype(np.uint8)
        if self.blend == "xor":
            return (bg ^ text).astype(np.uint8)
        if self.blend == "over":
            return (bg | text).astype(np.uint8)
        halo = dilate(text, 1)                 # outline: knock out a 1-dot halo
        return ((bg & (1 - halo)) | text).astype(np.uint8)

    # intro ----------------------------------------------------------
    def _intro(self, p, t):
        c = np.zeros((self.h, self.w), np.uint8)
        kind, s = self.intro, self.speed

        if kind == "type":
            shown = int(t * s / 0.09)
            for g in self.order[:shown]:
                blit(c, g.bmp, g.x, g.y)
            nxt = self.order[shown] if shown < len(self.order) else (self.order[-1] if self.order else None)
            if nxt is not None and int(t * 4) % 2 == 0:
                cx = nxt.x + (nxt.w + 1 if shown >= len(self.order) else 0)
                c[max(0, nxt.y):min(self.h, nxt.y + nxt.h),
                  max(0, cx):min(self.w, cx + max(2, nxt.w))] = 1
            return c

        if kind in ("decode", "flap"):
            step = int(t * s / 0.07)
            for g in self.order:
                if kind == "decode":
                    lock = (0.5 + g.i * 0.05) / s
                    if t >= lock:
                        blit(c, g.bmp, g.x, g.y)
                    elif t > g.i * 0.02 / s:
                        rng = _rng(self.spec, "d", g.i, step)
                        blit_in_box(c, _char_bitmap(self.spec, NOISE_CH[rng.integers(len(NOISE_CH))]), g)
                else:
                    start = g.i * 0.03 / s
                    k = int((t - start) * s / 0.07)
                    if k < 0:
                        continue
                    target = g.ch.upper()
                    if target in FLAP_SEQ:
                        idx = FLAP_SEQ.index(target)
                        steps = 6 + int(self.glyph_rand[g.i % len(self.glyph_rand)] * 6)
                        if k >= steps:
                            blit(c, g.bmp, g.x, g.y)
                        else:
                            ch = FLAP_SEQ[(idx - steps + k) % len(FLAP_SEQ)]
                            if ch != " ":
                                blit_in_box(c, _char_bitmap(self.spec, ch), g)
                    elif k >= 4:
                        blit(c, g.bmp, g.x, g.y)
            return c

        if kind in ("drop", "rise"):
            for g in self.order:
                q = (t - g.i * self._stagger()) / ((0.9 if kind == "drop" else 0.6) / s)
                if q <= 0:
                    continue
                if kind == "drop":
                    y = g.y - (1 - ease_out_bounce(q)) * (g.y + g.h)
                else:
                    y = g.y + (1 - ease_out_back(q)) * (self.h - g.y)
                blit(c, g.bmp, g.x, y)
            return c

        if kind == "dissolve":
            self._plot(c, self.px[self.px_rand < p])
            return c

        if kind == "gather":
            q = np.clip((p * 1.3 - self.px_rand * 0.3), 0, 1)
            e = 1 - (1 - q) ** 3
            pos = self.px_from + (self.px - self.px_from) * e[:, None]
            self._plot(c, pos)
            return c

        if kind == "wipe":
            edge = int(p * (self.w + 1))
            c[:, :edge] = self.final[:, :edge]
            if 0 <= edge < self.w:
                c[:, edge] = 1
            return c

        if kind.startswith("slide_"):
            left = int(round((1 - p) * self._slide_dist()))
            ox, oy = {"slide_left": (left, 0), "slide_right": (-left, 0),
                      "slide_up": (0, left), "slide_down": (0, -left)}.get(kind, (0, 0))
            for g in self.glyphs:
                blit(c, g.bmp, g.x + ox, g.y + oy)
            return c

        return self.final.copy()

    # idle -----------------------------------------------------------
    def _idle(self, tau):
        kind = self.idle
        if not kind:
            return self.final.copy()
        c = np.zeros((self.h, self.w), np.uint8)

        if kind == "wave":
            amp = max(1, round(max((g.h for g in self.glyphs), default=7) / 7))
            for g in self.glyphs:
                blit(c, g.bmp, g.x, g.y + round(amp * math.sin(tau * 2 * math.pi * 0.8 * self.speed - g.i * 0.6)))
            return c

        if kind == "jitter":
            step = int(tau * 6 * self.speed)
            for g in self.glyphs:
                r = _rng(self.spec, "j", g.i, step)
                blit(c, g.bmp, g.x + int(r.integers(-1, 2)), g.y + int(r.integers(-1, 2)))
            return c

        if kind == "sparkle":
            step = int(tau * 10 * self.speed)
            r = _rng(self.spec, "s", step)
            halo = dilate(self.final, 2) & (1 - self.final)
            ys, xs = np.nonzero(halo)
            if len(xs):
                pick = r.random(len(xs)) < 0.06
                c[ys[pick], xs[pick]] = 1
            return c | self.final

        if kind == "bounce":
            bx, by, bw, bh = self.box
            sx, sy = max(1, self.w - bw), max(1, self.h - bh)
            v = 14 * self.speed
            ox = _tri(bx + tau * v, sx) - bx
            oy = _tri(by + tau * v * 0.6, sy) - by
            for g in self.glyphs:
                blit(c, g.bmp, g.x + ox, g.y + oy)
            return c

        if kind == "marquee":
            c |= self.final
            step = int(tau * 12 * self.speed)
            per = _perimeter(self.w, self.h)
            lit = ((np.arange(len(per)) + step) // 2) % 3 == 0
            pts = per[lit]
            c[pts[:, 1], pts[:, 0]] = 1
            return c

        return self.final.copy()

    # outro ----------------------------------------------------------
    def _outro(self, p, tau):
        c = np.zeros((self.h, self.w), np.uint8)
        kind, s = self.outro, self.speed

        if kind == "dissolve":
            self._plot(c, self.px[self.px_rand >= p])
            return c

        if kind == "explode":
            tt = tau * s
            pos = self.px + self.px_vel * tt + np.array([0, 60.0]) * 0.5 * tt * tt
            self._plot(c, pos)
            return c

        if kind == "fall":
            order = np.argsort(self.glyph_rand[:len(self.glyphs)])
            for rank, gi in enumerate(order):
                g = self.glyphs[gi]
                tt = max(0.0, tau - rank * 0.04 / s) * s
                blit(c, g.bmp, g.x, g.y + 0.5 * 120 * tt * tt)
            return c

        if kind == "wipe":
            edge = int(p * (self.w + 1))
            c[:, edge:] = self.final[:, edge:]
            if 0 <= edge < self.w:
                c[:, edge] = 1
            return c

        if kind == "type":
            gone = int(tau * s / 0.05)
            keep = self.order[:max(0, len(self.order) - gone)]
            for g in keep:
                blit(c, g.bmp, g.x, g.y)
            return c

        if kind == "flap":
            for g in self.order:
                k = int((tau - g.i * 0.03 / s) * s / 0.07)
                if k < 0:
                    blit(c, g.bmp, g.x, g.y)
                    continue
                target = g.ch.upper()
                if k >= 8 or target not in FLAP_SEQ:
                    continue
                ch = FLAP_SEQ[(FLAP_SEQ.index(target) + k + 1) % len(FLAP_SEQ)]
                if ch != " ":
                    blit_in_box(c, _char_bitmap(self.spec, ch), g)
            return c

        return c

    # ----------------------------------------------------------------
    def _plot(self, c, pos):
        if not len(pos):
            return
        xy = np.round(pos).astype(int)
        ok = (xy[:, 0] >= 0) & (xy[:, 0] < self.w) & (xy[:, 1] >= 0) & (xy[:, 1] < self.h)
        xy = xy[ok]
        c[xy[:, 1], xy[:, 0]] = 1


def _tri(x, span):
    """Triangle wave bouncing between 0 and span."""
    m = x % (2 * span)
    return int(round(m if m <= span else 2 * span - m))


_perim_cache = {}


def _perimeter(w, h):
    k = (w, h)
    if k not in _perim_cache:
        pts = [(x, 0) for x in range(w)] + [(w - 1, y) for y in range(1, h)] + \
              [(x, h - 1) for x in range(w - 2, -1, -1)] + [(0, y) for y in range(h - 2, 0, -1)]
        _perim_cache[k] = np.array(pts, dtype=int)
    return _perim_cache[k]


def text_fx_frames(spec, w, h, duration=None):
    """Entry point used by renderer for text specs with intro/idle/outro/bg."""
    motion = spec.get("motion", "static") or "static"
    if motion.startswith("scroll_") and not motion.startswith("scroll_in_") and spec.get("bg"):
        # A scrolling message over a visual: let the classic text renderer do
        # the scrolling and composite its output over the background.
        yield from _scroll_over_bg(spec, w, h)
        return
    yield from TextFX(spec, w, h, duration).frames()


def _scroll_over_bg(spec, w, h):
    from clip import Clip
    from renderer import MAX_FPS
    plain = {k: v for k, v in spec.items() if k not in ("bg", "intro", "idle", "outro")}
    text_clip = Clip(plain, w, h, loop=True)
    fx = TextFX({**spec, "intro": "", "idle": "", "outro": "", "text": ""}, w, h)
    dt = 1.0 / max(4.0, MAX_FPS)
    t = 0.0
    while True:
        yield fx._composite(text_clip.at(t).astype(np.uint8), t), dt
        t += dt
