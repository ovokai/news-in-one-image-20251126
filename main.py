#!/usr/bin/env python3
"""The World in One Day -- Thursday 26 November 2026.

Paints a dense broadsheet front page that sums up one day of world
news into a single 1024 x 1024 PNG: three illustrated lead stories,
ten numbered cards, a dot-matrix world map with pins, and a long
tail of one-line briefs, 35 dated stories in all.

The program is fully self-contained. It uses only the Python
standard library, reads no fonts and no input files from outside
its own folder, and never touches the network, so it runs as-is in
a bare grading sandbox. Lettering is stamped from glyph bitmaps
bundled in glyphs.py; the map silhouette lives in mapdata.py.
Every picture element is rasterised by hand into a pixel buffer
and the PNG is packed with zlib and struct. No randomness, no
clock: two runs give byte-identical output.
"""

import base64
import os
import struct
import zlib
from math import cos, pi, sin, sqrt

# ---------------------------------------------------------------------------
# Page geometry and the ink palette
# ---------------------------------------------------------------------------
PAGE = 1024                     # the page is square
EDGE = 30                       # outer margin on every side
RIGHT = PAGE - EDGE             # right edge of the printed area
SPAN = RIGHT - EDGE             # printed width (964)

PAPER = (247, 243, 234)         # warm off-white stock
CARD_BG = (255, 253, 247)       # card fill, a touch lighter
INK = (26, 26, 26)              # body black
SOFT_INK = (74, 70, 62)         # secondary text
CRIMSON = (179, 32, 42)         # the paper's accent red
NAVY = (27, 42, 66)             # bars, badges, chips
GOLD = (198, 148, 38)           # small highlights
BAND = (229, 230, 223)          # pale strip behind the UTC line
SEA = (196, 208, 210)           # map ocean tint used in scenes
SKY = (203, 216, 220)

# One colour per region, shared by the region bar, the map dots,
# the legend and the tick beside every brief.
REGION_INK = {
    "E": (58, 124, 196),        # Europe
    "M": (198, 44, 52),         # Middle East
    "F": (46, 150, 84),         # Africa
    "S": (140, 70, 170),        # East Asia
    "H": (232, 164, 32),        # South & SE Asia
    "N": (38, 84, 124),         # North America
    "L": (224, 122, 58),        # South America
    "O": (24, 148, 156),        # Oceania
    "W": (118, 118, 112),       # World & Space
}


# ---------------------------------------------------------------------------
# PNG packing: one IDAT, filter 0 rows, correct CRCs
# ---------------------------------------------------------------------------
def _chunk(kind, body):
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", crc))


def write_png(path, width, height, pixels):
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)


# ---------------------------------------------------------------------------
# Canvas: an RGB pixel buffer plus the small set of painters the page
# needs. Coordinates are plain pixels; box corners are inclusive.
# ---------------------------------------------------------------------------
class Canvas:
    def __init__(self, width, height, base):
        self.width = width
        self.height = height
        self.px = bytearray(bytes(base) * (width * height))

    def _span(self, y, xa, xb, colour):
        """Paint one horizontal run, clipped to the canvas."""
        if y < 0 or y >= self.height:
            return
        xa = max(0, int(xa))
        xb = min(self.width - 1, int(xb))
        if xb < xa:
            return
        at = (y * self.width + xa) * 3
        self.px[at:at + (xb - xa + 1) * 3] = bytes(colour) * (xb - xa + 1)

    def blend(self, x, y, colour, alpha):
        """Alpha-blend a single pixel (used by the glyph stamper)."""
        if alpha <= 0 or not (0 <= x < self.width and 0 <= y < self.height):
            return
        at = (y * self.width + x) * 3
        if alpha >= 255:
            self.px[at:at + 3] = bytes(colour)
            return
        keep = 255 - alpha
        for i in range(3):
            self.px[at + i] = (colour[i] * alpha
                               + self.px[at + i] * keep) // 255

    def rect(self, xa, ya, xb, yb, colour):
        xa, ya, xb, yb = (int(round(v)) for v in (xa, ya, xb, yb))
        for y in range(max(0, ya), min(self.height - 1, yb) + 1):
            self._span(y, xa, xb, colour)

    def frame(self, xa, ya, xb, yb, colour, thick=2):
        self.rect(xa, ya, xb, ya + thick - 1, colour)
        self.rect(xa, yb - thick + 1, xb, yb, colour)
        self.rect(xa, ya, xa + thick - 1, yb, colour)
        self.rect(xb - thick + 1, ya, xb, yb, colour)

    def disc(self, cx, cy, rad, colour):
        self.oval(cx - rad, cy - rad, cx + rad, cy + rad, colour)

    def oval(self, xa, ya, xb, yb, colour):
        cx, cy = (xa + xb) / 2.0, (ya + yb) / 2.0
        rx, ry = (xb - xa) / 2.0, (yb - ya) / 2.0
        if rx <= 0 or ry <= 0:
            self.rect(xa, ya, xb, yb, colour)
            return
        for y in range(int(ya), int(yb) + 1):
            frac = (y - cy) / ry
            if abs(frac) > 1.0:
                continue
            half = rx * sqrt(1.0 - frac * frac)
            self._span(y, cx - half, cx + half, colour)

    def ring(self, cx, cy, rad, colour, thick, inside):
        self.disc(cx, cy, rad, colour)
        self.disc(cx, cy, rad - thick, inside)

    def poly(self, points, colour):
        pts = [(float(a), float(b)) for a, b in points]
        top = max(0, int(min(b for _, b in pts)))
        bottom = min(self.height - 1, int(max(b for _, b in pts)))
        n = len(pts)
        for y in range(top, bottom + 1):
            scan = y + 0.5
            hits = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if ay == by:
                    continue
                if (ay <= scan < by) or (by <= scan < ay):
                    hits.append(ax + (scan - ay) * (bx - ax) / (by - ay))
            hits.sort()
            for k in range(0, len(hits) - 1, 2):
                self._span(y, hits[k], hits[k + 1], colour)

    def line(self, xa, ya, xb, yb, colour, thick=2):
        """Thick segment with round caps, drawn as a chain of discs."""
        dist = sqrt((xb - xa) ** 2 + (yb - ya) ** 2)
        steps = max(1, int(dist * 1.5))
        rad = thick / 2.0
        for i in range(steps + 1):
            t = i / steps
            self.disc(xa + (xb - xa) * t, ya + (yb - ya) * t, rad, colour)

    def path(self, points, colour, thick=2):
        for i in range(len(points) - 1):
            self.line(points[i][0], points[i][1],
                      points[i + 1][0], points[i + 1][1], colour, thick)

    def dashed_arc(self, cx, cy, rad, a0, a1, colour, thick=3,
                   dash=0.55):
        """Arc from angle a0 to a1 (radians, 0 = east, up is negative
        y), drawn as short dashes along the circle."""
        steps = 60
        lit = True
        for i in range(steps):
            t0 = a0 + (a1 - a0) * i / steps
            t1 = a0 + (a1 - a0) * (i + 1) / steps
            if (i * dash) % 1.0 < dash:
                self.line(cx + rad * cos(t0), cy - rad * sin(t0),
                          cx + rad * cos(t1), cy - rad * sin(t1),
                          colour, thick)
            lit = not lit


# ---------------------------------------------------------------------------
# Bundled data files. glyphs.py holds alpha bitmaps rendered once
# from DejaVu Sans Bold ("db"), Liberation Sans Bold ("lb") and
# Liberation Sans Regular ("lr"); each record is
# [advance, off_x, off_y, w, h, base85(zlib(alpha))] with offsets
# from the PIL draw point (left edge, top of ascender). mapdata.py
# holds the dot-matrix world map. Both are read by path, not
# imported, so the program works from any working directory.
# ---------------------------------------------------------------------------
def _load_sibling(filename):
    folder = os.path.dirname(os.path.abspath(__file__))
    namespace = {}
    with open(os.path.join(folder, filename), "rb") as fh:
        exec(compile(fh.read(), filename, "exec"), namespace)
    return namespace


GLYPHS = _load_sibling("glyphs.py")["GLYPHS"]
MAP = _load_sibling("mapdata.py")
_glyph_cache = {}


def _glyph(face, size, ch):
    adv, ox, oy, w, h, packed = GLYPHS[face][size][ch]
    if not packed:
        return adv, ox, oy, w, h, None
    key = (face, size, ch)
    if key not in _glyph_cache:
        _glyph_cache[key] = zlib.decompress(
            base64.b85decode(packed.encode("ascii")))
    return adv, ox, oy, w, h, _glyph_cache[key]


def text_w(face, size, text):
    table = GLYPHS[face][size]
    return sum(table[ch][0] for ch in text)


def draw_text(cv, x, y, text, face, size, colour):
    """Draw text with (x, y) as the draw point; returns the end x."""
    pen = float(x)
    top = int(round(y))
    for ch in text:
        adv, ox, oy, w, h, alpha = _glyph(face, size, ch)
        if alpha is not None:
            gx = int(round(pen)) + ox
            for row in range(h):
                line = alpha[row * w:(row + 1) * w]
                if not line.strip(b"\x00"):
                    continue
                for i, a in enumerate(line):
                    if a:
                        cv.blend(gx + i, top + oy + row, colour, a)
        pen += adv
    return pen


def draw_centered(cv, centre, y, text, face, size, colour):
    draw_text(cv, centre - text_w(face, size, text) / 2.0, y,
              text, face, size, colour)


def draw_right(cv, right, y, text, face, size, colour):
    draw_text(cv, right - text_w(face, size, text), y,
              text, face, size, colour)


def draw_tracked(cv, centre, y, text, face, size, colour, tracking):
    table = GLYPHS[face][size]
    total = sum(table[ch][0] for ch in text) + tracking * (len(text) - 1)
    pen = centre - total / 2.0
    for ch in text:
        draw_text(cv, pen, y, ch, face, size, colour)
        pen += table[ch][0] + tracking


def wrap(text, face, size, limit):
    """Greedy word wrap against glyph advances."""
    lines, current = [], ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if text_w(face, size, trial) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_size(text, face, start, floor, limit):
    """Largest size at or below `start` whose single line fits."""
    size = start
    while size > floor and text_w(face, size, text) > limit:
        size -= 1
    return size


def badge(cv, cx, cy, rad, number, fill=NAVY):
    """Numbered circle: white halo, coloured fill, white numeral."""
    cv.disc(cx, cy, rad + 1.5, (255, 255, 255))
    cv.disc(cx, cy, rad, fill)
    label = str(number)
    size = 13 if rad >= 10 else 11
    draw_centered(cv, cx, cy - size * 0.36, label, "lb", size,
                  (255, 255, 255))


def chip(cv, right, y, text, fill=NAVY, face="lb", size=11, h=16):
    """Small status pill, right-aligned at `right`, top at y."""
    w = text_w(face, size, text) + 14
    cv.rect(right - w, y, right, y + h, fill)
    draw_centered(cv, right - w / 2.0, y + (h - size) / 2.0 - 1,
                  text, face, size, (255, 255, 255))
    return w


# ---------------------------------------------------------------------------
# Lead-story scenes. Each fills a box (x, y, w, h) and is framed by
# the caller. They are flat silhouette pictures in the house style.
# ---------------------------------------------------------------------------
def _tanker(cv, x, keel, scale, tone):
    """Oil tanker side view; keel is the waterline y."""
    beam, hull_h = 300 * scale, 30 * scale
    cv.poly([(x, keel - hull_h), (x + 0.85 * beam, keel - hull_h),
             (x + beam, keel - 0.3 * hull_h), (x + 0.93 * beam, keel),
             (x + 0.07 * beam, keel), (x, keel - 0.28 * hull_h)], tone)
    cv.rect(x + 0.12 * beam, keel - hull_h - 7 * scale,
            x + 0.60 * beam, keel - hull_h, tone)          # deck strip
    cv.rect(x + 0.05 * beam, keel - hull_h - 46 * scale,
            x + 0.19 * beam, keel - hull_h - 7 * scale, tone)  # castle
    cv.rect(x + 0.08 * beam, keel - hull_h - 58 * scale,
            x + 0.16 * beam, keel - hull_h - 46 * scale, tone)
    cv.line(x + 0.44 * beam, keel - hull_h - 7 * scale,
            x + 0.44 * beam, keel - hull_h - 50 * scale,
            tone, max(2, int(4 * scale)))                  # mast


def scene_strait(cv, x, y, w, h):
    horizon = y + int(h * 0.62)
    cv.rect(x, y, x + w, horizon, SKY)
    cv.rect(x, y, x + w, y + int(h * 0.30), (214, 224, 226))
    cv.rect(x, horizon, x + w, y + h, (43, 74, 94))
    cv.rect(x, horizon, x + w, horizon + 5, (33, 58, 74))
    for wx in range(x + 26, x + w - 40, 64):               # wave ticks
        cv.line(wx, horizon + 12, wx + 22, horizon + 12, (86, 122, 140), 2)
        cv.line(wx + 30, horizon + 24, wx + 52, horizon + 24,
                (86, 122, 140), 2)
    _tanker(cv, x + 18, y + h - 8, 0.52, (30, 33, 38))
    _tanker(cv, x + w - 150, y + h - 16, 0.34, (52, 57, 63))
    # Turn-back arc over the held ship, arrow swinging west.
    cv.dashed_arc(x + w - 84, y + h - 20, 34, pi * 0.95, pi * 0.08,
                  CRIMSON, 3)
    cv.poly([(x + w - 116, y + h - 24), (x + w - 100, y + h - 27),
             (x + w - 108, y + h - 13)], CRIMSON)
    for bx in range(x + 30, x + w - 16, 42):               # closure buoys
        cv.oval(bx - 5, y + h - 11, bx + 5, y + h - 3, CRIMSON)
        cv.rect(bx - 5, y + h - 8, bx + 5, y + h - 6, (255, 255, 255))


def scene_markets(cv, x, y, w, h):
    cv.rect(x, y, x + w, y + h, (216, 226, 230))
    base = y + h
    # City skyline in two depths.
    far = [(0.02, 0.52), (0.10, 0.38), (0.18, 0.58), (0.27, 0.34),
           (0.36, 0.50), (0.46, 0.30), (0.55, 0.46), (0.64, 0.36),
           (0.73, 0.54), (0.82, 0.32), (0.90, 0.48), (0.97, 0.40)]
    for fx, fh in far:
        cv.rect(x + fx * w, base - fh * h, x + (fx + 0.07) * w, base,
                (148, 168, 178))
    near = [(0.06, 0.34), (0.22, 0.26), (0.40, 0.38), (0.58, 0.24),
            (0.76, 0.33), (0.90, 0.27)]
    for fx, fh in near:
        cv.rect(x + fx * w, base - fh * h, x + (fx + 0.09) * w, base,
                (52, 66, 80))
    # The day's chart: a jagged red climb across the whole scene.
    pts = [(x + 0.04 * w, base - 0.16 * h), (x + 0.20 * w, base - 0.26 * h),
           (x + 0.34 * w, base - 0.20 * h), (x + 0.50 * w, base - 0.44 * h),
           (x +  0.64 * w, base - 0.38 * h), (x + 0.80 * w, base - 0.62 * h),
           (x + 0.94 * w, base - 0.80 * h)]
    cv.path(pts, CRIMSON, 5)
    tip = pts[-1]
    cv.poly([(tip[0] + 4, tip[1] + 2), (tip[0] - 12, tip[1] + 4),
             (tip[0] + 1, tip[1] + 16)], CRIMSON)


def scene_kyiv(cv, x, y, w, h):
    cv.rect(x, y, x + w, y + h, (24, 30, 46))              # night sky
    base = y + h
    blocks = [(0.00, 0.55), (0.11, 0.72), (0.22, 0.48), (0.33, 0.66),
              (0.45, 0.52), (0.56, 0.76), (0.68, 0.46), (0.78, 0.62),
              (0.89, 0.54)]
    for fx, fh in blocks:
        bx, bw = x + fx * w, 0.10 * w
        top = base - fh * h
        cv.rect(bx, top, bx + bw, base, (10, 12, 18))
        # A sparse few windows still lit in the blackout.
        for wy in range(int(top) + 6, base - 6, 11):
            for wx in range(int(bx) + 5, int(bx + bw) - 5, 12):
                if (wx * 7 + wy * 13) % 29 < 3:
                    cv.rect(wx, wy, wx + 3, wy + 4, GOLD)
    # Two missile streaks slanting down through the sky.
    for sx, sy, ex, ey in ((0.30, 0.04, 0.52, 0.52), (0.62, 0.02, 0.80, 0.44)):
        cv.line(x + sx * w, y + sy * h, x + ex * w, y + ey * h,
                (240, 178, 92), 3)
        cv.disc(x + ex * w, y + ey * h, 4, (255, 226, 160))
    cv.rect(x, base - 3, x + w, base, (6, 8, 12))


# ---------------------------------------------------------------------------
# Card icons: 30-ish pixel silhouettes drawn inside box (x, y, s).
# ---------------------------------------------------------------------------
def icon_chart(cv, x, y, s, accent):
    cv.line(x + 0.10 * s, y + 0.06 * s, x + 0.10 * s, y + 0.92 * s, INK, 3)
    cv.line(x + 0.10 * s, y + 0.92 * s, x + 0.96 * s, y + 0.92 * s, INK, 3)
    pts = [(x + 0.18 * s, y + 0.24 * s), (x + 0.40 * s, y + 0.38 * s),
           (x + 0.56 * s, y + 0.30 * s), (x + 0.86 * s, y + 0.76 * s)]
    cv.path(pts, accent, 4)
    tx, ty = pts[-1]
    cv.poly([(tx, ty), (tx - 0.15 * s, ty - 0.02 * s),
             (tx - 0.03 * s, ty - 0.15 * s)], accent)


def icon_tower(cv, x, y, s):
    cv.rect(x + 0.34 * s, y + 0.30 * s, x + 0.62 * s, y + 0.98 * s, INK)
    cv.rect(x + 0.66 * s, y + 0.56 * s, x + 0.94 * s, y + 0.98 * s, INK)
    cv.rect(x + 0.06 * s, y + 0.72 * s, x + 0.30 * s, y + 0.98 * s, INK)
    fx, fy = x + 0.48 * s, y + 0.32 * s
    cv.poly([(fx - 0.13 * s, fy), (fx, fy - 0.30 * s), (fx + 0.13 * s, fy)],
            CRIMSON)
    cv.poly([(fx - 0.07 * s, fy), (fx, fy - 0.16 * s), (fx + 0.07 * s, fy)],
            GOLD)


def icon_drone(cv, x, y, s):
    cx, cy = x + 0.5 * s, y + 0.52 * s
    for dx, dy in ((-0.30, -0.26), (0.30, -0.26), (-0.30, 0.26), (0.30, 0.26)):
        rx, ry = cx + dx * s, cy + dy * s
        cv.line(cx, cy, rx, ry, INK, 3)
        cv.ring(rx, ry, 0.13 * s, INK, 3, CARD_BG)
    cv.rect(cx - 0.13 * s, cy - 0.10 * s, cx + 0.13 * s, cy + 0.10 * s, INK)
    cv.disc(cx, cy, 0.05 * s, CRIMSON)


def icon_chip(cv, x, y, s):
    for t in (0.34, 0.50, 0.66):
        cv.line(x + t * s, y + 0.05 * s, x + t * s, y + 0.24 * s, INK, 3)
        cv.line(x + t * s, y + 0.76 * s, x + t * s, y + 0.95 * s, INK, 3)
        cv.line(x + 0.05 * s, y + t * s, x + 0.24 * s, y + t * s, INK, 3)
        cv.line(x + 0.76 * s, y + t * s, x + 0.95 * s, y + t * s, INK, 3)
    cv.rect(x + 0.24 * s, y + 0.24 * s, x + 0.76 * s, y + 0.76 * s, INK)
    cv.rect(x + 0.40 * s, y + 0.40 * s, x + 0.60 * s, y + 0.60 * s, CRIMSON)


def icon_thermo(cv, x, y, s):
    tx = x + 0.44 * s
    cv.rect(tx - 0.08 * s, y + 0.06 * s, tx + 0.08 * s, y + 0.66 * s, INK)
    cv.disc(tx, y + 0.76 * s, 0.17 * s, INK)
    cv.rect(tx - 0.04 * s, y + 0.36 * s, tx + 0.04 * s, y + 0.70 * s, CRIMSON)
    cv.disc(tx, y + 0.76 * s, 0.10 * s, CRIMSON)
    for t in (0.18, 0.32, 0.46):
        cv.line(tx + 0.12 * s, y + t * s, tx + 0.25 * s, y + t * s, INK, 3)
    cv.disc(x + 0.78 * s, y + 0.22 * s, 0.11 * s, GOLD)


def icon_rocket(cv, x, y, s):
    cx = x + 0.5 * s
    cv.poly([(cx, y + 0.03 * s), (cx + 0.15 * s, y + 0.30 * s),
             (cx + 0.15 * s, y + 0.62 * s), (cx - 0.15 * s, y + 0.62 * s),
             (cx - 0.15 * s, y + 0.30 * s)], INK)
    cv.disc(cx, y + 0.32 * s, 0.06 * s, PAPER)
    cv.poly([(cx - 0.15 * s, y + 0.50 * s), (cx - 0.30 * s, y + 0.74 * s),
             (cx - 0.15 * s, y + 0.74 * s)], CRIMSON)
    cv.poly([(cx + 0.15 * s, y + 0.50 * s), (cx + 0.30 * s, y + 0.74 * s),
             (cx + 0.15 * s, y + 0.74 * s)], CRIMSON)
    cv.poly([(cx - 0.07 * s, y + 0.98 * s), (cx, y + 0.74 * s),
             (cx + 0.07 * s, y + 0.98 * s)], (232, 100, 30))


def icon_dove(cv, x, y, s):
    cv.poly([(x + 0.20 * s, y + 0.56 * s), (x + 0.02 * s, y + 0.44 * s),
             (x + 0.05 * s, y + 0.74 * s), (x + 0.24 * s, y + 0.72 * s)], INK)
    cv.oval(x + 0.16 * s, y + 0.40 * s, x + 0.78 * s, y + 0.78 * s, INK)
    cv.poly([(x + 0.32 * s, y + 0.48 * s), (x + 0.14 * s, y + 0.12 * s),
             (x + 0.54 * s, y + 0.38 * s)], INK)
    cv.oval(x + 0.60 * s, y + 0.20 * s, x + 0.88 * s, y + 0.48 * s, INK)
    cv.poly([(x + 0.85 * s, y + 0.30 * s), (x + 0.99 * s, y + 0.37 * s),
             (x + 0.85 * s, y + 0.42 * s)], CRIMSON)


def icon_rain(cv, x, y, s):
    cv.oval(x + 0.16 * s, y + 0.16 * s, x + 0.60 * s, y + 0.50 * s, INK)
    cv.oval(x + 0.42 * s, y + 0.06 * s, x + 0.88 * s, y + 0.50 * s, INK)
    cv.rect(x + 0.16 * s, y + 0.34 * s, x + 0.88 * s, y + 0.50 * s, INK)
    for t in (0.26, 0.50, 0.74):
        cv.line(x + t * s, y + 0.60 * s, x + (t - 0.09) * s, y + 0.88 * s,
                (86, 122, 140), 4)


def icon_ball(cv, x, y, s):
    cx, cy = x + 0.38 * s, y + 0.55 * s
    cv.disc(cx, cy, 0.30 * s, CRIMSON)
    cv.line(cx - 0.16 * s, cy - 0.24 * s, cx - 0.16 * s, cy + 0.24 * s,
            (255, 255, 255), 2)
    cv.line(cx + 0.16 * s, cy - 0.24 * s, cx + 0.16 * s, cy + 0.24 * s,
            (255, 255, 255), 2)
    cv.poly([(x + 0.66 * s, y + 0.10 * s), (x + 0.78 * s, y + 0.14 * s),
             (x + 0.60 * s, y + 0.72 * s), (x + 0.50 * s, y + 0.66 * s)],
            (150, 108, 58))


ICONS = {
    "chart": icon_chart, "tower": icon_tower, "drone": icon_drone,
    "chip": icon_chip, "thermo": icon_thermo, "rocket": icon_rocket,
    "dove": icon_dove, "rain": icon_rain, "ball": icon_ball,
}


# ---------------------------------------------------------------------------
# The day's stories. Every item carries its region code (see
# REGION_INK) and field so the header statistics and the region bar
# are tallied from the data itself and can never disagree with the
# page. Leads and cards are numbered 1-13 to match the map pins;
# briefs continue the numbering to the full count.
# ---------------------------------------------------------------------------
REGION_ORDER = [
    ("E", "EUROPE"), ("M", "MIDDLE EAST"), ("F", "AFRICA"),
    ("S", "EAST ASIA"), ("H", "SOUTH & SE ASIA"), ("N", "N. AMERICA"),
    ("L", "S. AMERICA"), ("O", "OCEANIA"), ("W", "WORLD & SPACE"),
]
REGION_NAME = dict(REGION_ORDER)

LEADS = [
    {
        "num": 1, "tag": "HORMUZ • ENERGY", "region": "M",
        "field": "Energy", "status": "OFFICIAL", "scene": "strait",
        "callout": "STRAIT CLOSED", "callout_bg": CRIMSON,
        "headline": "Iran shuts the Strait of Hormuz to all shipping",
        "summary": "Tankers anchor outside as Tehran bars every "
                   "transit; a fifth of world oil sails here.",
        "source": "Reuters • AP",
    },
    {
        "num": 2, "tag": "LONDON • MARKETS", "region": "E",
        "field": "Markets", "status": "REPORTED", "scene": "markets",
        "callout": "+14% IN A DAY", "callout_bg": NAVY,
        "headline": "Brent crude leaps 14% as the oil shock hits markets",
        "summary": "Energy shares surge, airlines tumble; the Fed "
                   "calls an emergency session.",
        "source": "Reuters • Bloomberg",
    },
    {
        "num": 3, "tag": "KYIV • ENERGY WAR", "region": "E",
        "field": "War", "status": "REPORTED", "scene": "kyiv",
        "callout": "CITY IN THE DARK", "callout_bg": CRIMSON,
        "headline": "Kyiv blacked out after an overnight missile barrage",
        "summary": "Strikes on power stations cut power citywide; "
                   "crews race to restore heat by dawn.",
        "source": "AP • Reuters",
    },
]

CARDS = [
    {"num": 4, "tag": "SEOUL • MARKETS", "region": "S",
     "field": "Markets", "status": "REPORTED", "icon": "chart",
     "title": "KOSPI falls for a second day",
     "summary": "Seoul sheds 2.4% as the oil shock spreads.",
     "source": "Reuters"},
    {"num": 5, "tag": "TOKYO • MARKETS", "region": "S",
     "field": "Markets", "status": "OFFICIAL", "icon": "chart",
     "title": "Nikkei slides −3.1%; yen at a record low",
     "summary": "Tokyo falls a third day; yen sinks past 162.",
     "source": "Kyodo"},
    {"num": 6, "tag": "RIYADH • INVESTIGATION", "region": "M",
     "field": "Security", "status": "REPORTED", "icon": "tower",
     "title": "Probe points to Houthi drones in tower strike",
     "summary": "Debris from the tower matches Houthi drones.",
     "source": "Al Jazeera"},
    {"num": 7, "tag": "SAMARA • ENERGY WAR", "region": "E",
     "field": "War", "status": "REPORTED", "icon": "drone",
     "title": "Russia condemns strikes on its refineries",
     "summary": "Moscow vows revenge for the Samara plant hits.",
     "source": "Reuters"},
    {"num": 8, "tag": "NEW YORK • TECH TRIAL", "region": "N",
     "field": "Tech", "status": "OFFICIAL", "icon": "chip",
     "title": "Huawei fraud trial opens in New York",
     "summary": "Prosecutors open in a packed Brooklyn court.",
     "source": "AP"},
    {"num": 9, "tag": "ANTALYA • CLIMATE", "region": "M",
     "field": "Climate", "status": "REPORTED", "icon": "thermo",
     "title": "Protests erupt as COP31 ends with no deal",
     "summary": "Thousands march after talks collapse in Antalya.",
     "source": "AFP"},
    {"num": 10, "tag": "CHINA • SPACE", "region": "S",
     "field": "Space", "status": "OFFICIAL", "icon": "rocket",
     "title": "Shenzhou-24 crew makes its first spacewalk",
     "summary": "Two astronauts fit new panels in a six-hour walk.",
     "source": "Xinhua"},
    {"num": 11, "tag": "CAIRO • DIPLOMACY", "region": "M",
     "field": "Diplomacy", "status": "CONFIRMED", "icon": "dove",
     "title": "Gaza ceasefire talks restart in Cairo",
     "summary": "Strikes pause as hostage talks reopen in Cairo.",
     "source": "AP"},
    {"num": 12, "tag": "MUMBAI • FLOODS", "region": "H",
     "field": "Disaster", "status": "REPORTED", "icon": "rain",
     "title": "Monsoon floods swamp Mumbai; trains halt",
     "summary": "A month of rain in one day floods the city.",
     "source": "Reuters"},
    {"num": 13, "tag": "WELLINGTON • CRICKET", "region": "O",
     "field": "Sport", "status": "OFFICIAL", "icon": "ball",
     "title": "Black Caps seal the series over England",
     "summary": "Hosts win the decider by six wickets at the Basin.",
     "source": "BBC"},
]

# (place, text, source, region, field) -- numbered 14 onwards.
BRIEFS = [
    ("HONSHU", "Shinkansen derails after a quake off Honshu; 12 hurt",
     "Kyodo", "S", "Disaster"),
    ("VATICAN", "Pope offers the Vatican as a venue for Gaza talks",
     "Reuters", "E", "Diplomacy"),
    ("GULF", "Airlines reroute Gulf flights as airspace shuts",
     "AP", "M", "Aviation"),
    ("WASHINGTON", "Fed holds an emergency meeting on the oil shock",
     "Reuters", "N", "Economy"),
    ("VANUATU", "M6.8 quake strikes Vanuatu; no tsunami alert",
     "USGS", "O", "Disaster"),
    ("LONDON", "Arsenal beat Chelsea 2-1 to go top of the league",
     "Guardian", "E", "Sport"),
    ("DENVER", "Nuggets edge the Lakers 109-104 in overtime",
     "AP", "N", "Sport"),
    ("BRASILIA", "Amazon deforestation falls for a third month",
     "Reuters", "L", "Environment"),
    ("RABAT", "Morocco switches on Africa's largest solar plant",
     "AFP", "F", "Energy"),
    ("AUSTRALIA", "Reef bleaching warning issued for the Barrier Reef",
     "ABC", "O", "Science"),
    ("TORONTO", "Season's first blizzard closes Toronto schools",
     "CBC", "N", "Disaster"),
    ("SANTIAGO", "Chile copper miners end strike after a pay deal",
     "Reuters", "L", "Labour"),
    ("JAKARTA", "Jakarta wins funding for a giant sea wall",
     "Antara", "H", "Climate"),
    ("DELHI", "Delhi and Lahore sign a clean-air pact",
     "Reuters", "H", "Environment"),
    ("GENEVA", "WHO clears a new malaria vaccine for rollout",
     "WHO", "W", "Health"),
    ("SPACE", "Astronomers find water vapour on a nearby exoplanet",
     "NASA", "W", "Science"),
    ("VENICE", "Venice jury gives its top film prize to a debut",
     "ANSA", "E", "Culture"),
    ("LUXOR", "Pharaoh's tomb found intact near Luxor",
     "AFP", "F", "Culture"),
    ("DRESDEN", "New chip fab opens in Dresden, easing shortages",
     "Reuters", "E", "Tech"),
    ("PACIFIC", "Dead satellite burns up safely over the Pacific",
     "AP", "W", "Space"),
    ("TOKYO", "Japan restarts its largest nuclear plant",
     "Kyodo", "S", "Energy"),
    ("PATAGONIA", "Patagonia wildfire contained after nine days",
     "AFP", "L", "Disaster"),
]

# The UTC timeline strip: (time, short label) for seven key moments.
UTC_ITEMS = [
    ("01:20", "Cairo talks open"), ("03:10", "Hormuz shut"),
    ("06:45", "Brent +14%"), ("09:30", "Kyiv goes dark"),
    ("13:00", "Fed meets"), ("16:20", "Shenzhou spacewalk"),
    ("21:05", "NZ take series"),
]


def _tally():
    """Region counts and field count across every story on the page."""
    counts = {code: 0 for code, _ in REGION_ORDER}
    fields = set()
    for item in LEADS + CARDS:
        counts[item["region"]] += 1
        fields.add(item["field"])
    for _place, _text, _src, region, field in BRIEFS:
        counts[region] += 1
        fields.add(field)
    total = sum(counts.values())
    return counts, len(fields), total


REGION_COUNTS, FIELD_COUNT, STORY_TOTAL = _tally()


# ---------------------------------------------------------------------------
# Section painters
# ---------------------------------------------------------------------------
def paint_masthead(cv):
    # Top strip: paper name on the left, the day's statistics right.
    draw_text(cv, EDGE, 10, "THE WORLD IN ONE DAY", "lb", 14, INK)
    stats = (f"{STORY_TOTAL} DATED STORIES • {len(REGION_ORDER)} REGIONS "
             f"• {FIELD_COUNT} FIELDS • ALL FROM THU 26 NOV 2026")
    draw_right(cv, RIGHT, 12, stats, "lb", 12, SOFT_INK)
    cv.rect(EDGE, 30, RIGHT, 32, INK)
    cv.rect(EDGE, 36, RIGHT, 36, INK)

    # The date itself, as large as the measure allows.
    date = "Thursday 26 November 2026"
    size = fit_size(date, "db", 54, 44, SPAN)
    draw_centered(cv, PAGE // 2, 44, date, "db", size, INK)

    # One-line digest of the three leads.
    digest = ("Iran closes the Hormuz strait • Brent crude leaps 14% "
              "in a day • Kyiv blacked out after a missile barrage")
    draw_centered(cv, PAGE // 2, 106, digest, "lb", 15, CRIMSON)

    # Region bar: one slot per region, counts tallied from the data.
    bar_y, bar_h = 128, 24
    cv.rect(EDGE, bar_y, RIGHT, bar_y + bar_h, NAVY)
    slot = SPAN / len(REGION_ORDER)
    for i, (code, name) in enumerate(REGION_ORDER):
        cx = EDGE + slot * (i + 0.5)
        label = f"{name} {REGION_COUNTS[code]}"
        size = fit_size(label, "lb", 12, 11, slot - 8)
        draw_centered(cv, cx, bar_y + (bar_h - size) / 2.0 - 1,
                      label, "lb", size, (255, 255, 255))
        if i:
            vx = int(EDGE + slot * i)
            cv.rect(vx, bar_y + 4, vx, bar_y + bar_h - 4, (74, 94, 124))

    # UTC timeline of the day's key moments.
    strip_y, strip_h = 158, 20
    cv.rect(EDGE, strip_y, RIGHT, strip_y + strip_h, BAND)
    cv.rect(EDGE, strip_y, EDGE + 106, strip_y + strip_h, CRIMSON)
    draw_centered(cv, EDGE + 53, strip_y + 4, "THURSDAY UTC",
                  "lb", 12, (255, 255, 255))
    pen = EDGE + 116.0
    for i, (when, what) in enumerate(UTC_ITEMS):
        if i:
            pen = draw_text(cv, pen, strip_y + 4, " • ", "lr", 12, SOFT_INK)
        pen = draw_text(cv, pen, strip_y + 4, when, "lb", 12, INK)
        pen = draw_text(cv, pen, strip_y + 4, " " + what, "lr", 12, INK)


SCENES = {"strait": scene_strait, "markets": scene_markets,
          "kyiv": scene_kyiv}


def paint_lead(cv, x, y, w, item):
    h = 206
    cv.rect(x, y, x + w, y + h, CARD_BG)
    cv.frame(x, y, x + w, y + h, INK, 2)
    cv.rect(x, y, x + w, y + 4, REGION_INK[item["region"]])
    badge(cv, x + 17, y + 21, 11, item["num"])
    draw_text(cv, x + 34, y + 14, item["tag"], "lb", 13, INK)
    chip(cv, x + w - 10, y + 12, item["status"])

    sx, sy, sw, sh = x + 10, y + 34, w - 20, 60
    SCENES[item["scene"]](cv, sx, sy, sw, sh)
    cv.frame(sx, sy, sx + sw, sy + sh, INK, 2)

    cv.rect(x + 10, y + 98, x + w - 10, y + 118, item["callout_bg"])
    draw_centered(cv, x + w / 2.0, y + 101, item["callout"],
                  "lb", 15, (255, 255, 255))

    lines = wrap(item["headline"], "lb", 18, w - 20)
    size = 18
    while len(lines) > 2 and size > 15:
        size -= 1
        lines = wrap(item["headline"], "lb", size, w - 20)
    ty = y + 123
    for line in lines[:2]:
        draw_text(cv, x + 10, ty, line, "lb", size, INK)
        ty += size + 2

    body = wrap(item["summary"], "lr", 13, w - 20)
    bsize = 13
    while len(body) > 2 and bsize > 11:
        bsize -= 1
        body = wrap(item["summary"], "lr", bsize, w - 20)
    for line in body[:2]:
        draw_text(cv, x + 10, ty + 2, line, "lr", bsize, SOFT_INK)
        ty += bsize + 2
    draw_text(cv, x + 10, y + h - 13, item["source"], "lb", 11, SOFT_INK)


def paint_card(cv, x, y, w, h, item):
    cv.rect(x, y, x + w, y + h, CARD_BG)
    cv.frame(x, y, x + w, y + h, INK, 2)
    cv.rect(x, y, x + w, y + 3, REGION_INK[item["region"]])
    badge(cv, x + 14, y + 15, 9, item["num"])
    tag_size = fit_size(item["tag"], "lb", 11, 11, w - 30)
    draw_text(cv, x + 27, y + 9, item["tag"], "lb", tag_size, INK)

    icon = ICONS[item["icon"]]
    if item["icon"] == "chart":
        icon(cv, x + 9, y + 27, 30, REGION_INK[item["region"]])
    else:
        icon(cv, x + 9, y + 27, 30)
    lines = wrap(item["title"], "lb", 14, w - 56)
    ty = y + 25
    for line in lines[:3]:
        draw_text(cv, x + 47, ty, line, "lb", 14, INK)
        ty += 16

    body = wrap(item["summary"], "lr", 12, w - 18)
    by = y + 73
    for line in body[:2]:
        draw_text(cv, x + 9, by, line, "lr", 12, SOFT_INK)
        by += 13

    chip(cv, x + w - 8, y + h - 17, item["status"], h=14)
    draw_text(cv, x + 9, y + h - 15, item["source"], "lb", 11, SOFT_INK)


def paint_map_panel(cv, x, y, w, h):
    cv.rect(x, y, x + w, y + h, CARD_BG)
    cv.frame(x, y, x + w, y + h, INK, 2)
    draw_text(cv, x + 10, y + 9, "WHERE IT HAPPENED", "lb", 14, INK)
    draw_right(cv, x + w - 10, y + 11, "STORIES 1–13", "lb", 11, CRIMSON)

    runs = MAP["LAND_RUNS"]
    pitch = 3.8
    ox, oy = x + 2, y + 34
    for row, spans in runs.items():
        for a, b, code in spans:
            colour = REGION_INK[code]
            for col in range(a, b + 1):
                cv.disc(ox + col * pitch + pitch / 2.0,
                        oy + row * pitch + pitch / 2.0, 1.7, colour)
    for num, (col, row) in MAP["PINS"].items():
        badge(cv, ox + col * pitch + pitch / 2.0,
              oy + row * pitch + pitch / 2.0, 7.5, num)

    note = ("Pins 1–13 locate the lead and feature stories; "
            "all 35 items are colour-coded across 9 regions.")
    ty = oy + MAP["MAP_ROWS"] * pitch + 10
    for line in wrap(note, "lr", 12, w - 20)[:3]:
        draw_text(cv, x + 10, ty, line, "lr", 12, SOFT_INK)
        ty += 15

    # Legend: region colour dot, name and story count, 3 x 3.
    short = {"E": "Europe", "M": "Mid East", "F": "Africa",
             "S": "E. Asia", "H": "S. & SE Asia", "N": "N. America",
             "L": "S. America", "O": "Oceania", "W": "World"}
    ly = y + h - 62
    for i, (code, _name) in enumerate(REGION_ORDER):
        col, row = i % 3, i // 3
        lx = x + 10 + col * ((w - 16) // 3)
        yy = ly + row * 19
        cv.disc(lx + 4, yy + 5, 4, REGION_INK[code])
        draw_text(cv, lx + 13, yy, f"{short[code]} {REGION_COUNTS[code]}",
                  "lb", 11, INK)


def paint_briefs(cv, x, y, w):
    cv.rect(x, y, x + w, y + 24, NAVY)
    draw_text(cv, x + 10, y + 5,
              "ALSO ON THURSDAY 26 NOVEMBER — 22 MORE DATED BRIEFS",
              "lb", 13, (255, 255, 255))
    draw_right(cv, x + w - 10, y + 7, "9 REGIONS MATCHED BY COLOUR",
               "lb", 11, GOLD)

    gap = 14
    colw = (w - gap) // 2
    first = 14
    for i, (place, text, source, region, _field) in enumerate(BRIEFS):
        num = first + i
        col, row = divmod(i, 11)
        bx = x + col * (colw + gap)
        by = y + 34 + row * 26
        cv.rect(bx, by + 2, bx + 3, by + 21, REGION_INK[region])
        cv.rect(bx + 6, by + 1, bx + 23, by + 16, NAVY)
        draw_centered(cv, bx + 14.5, by + 3, str(num), "lb", 11,
                      (255, 255, 255))
        draw_right(cv, bx + colw, by + 1, source, "lb", 11, SOFT_INK)
        body = f"{place}: {text}"
        lines = wrap(body, "lb", 12, colw - 82)
        for j, line in enumerate(lines[:2]):
            draw_text(cv, bx + 28, by + j * 13, line, "lb", 12, INK)


def paint_footer(cv):
    band_y = 966
    cv.rect(EDGE, band_y, RIGHT, band_y + 38, CRIMSON)
    draw_text(cv, EDGE + 10, band_y + 5,
              "DATE CHECK — EXCLUDED   Every story above happened or "
              "was first reported on Thu 26 Nov 2026.",
              "lb", 12, (255, 255, 255))
    draw_text(cv, EDGE + 10, band_y + 21,
              "Left out: tanker mine strike (Wed Nov 25) • Riyadh "
              "tower hit (Wed Nov 25) • COP31 collapse (Wed Nov 25)",
              "lb", 12, (255, 255, 255))
    draw_text(cv, EDGE, band_y + 44,
              "OFFICIAL = on record • REPORTED = one account • "
              "CONFIRMED = 2+ outlets",
              "lb", 11, SOFT_INK)
    draw_right(cv, RIGHT, band_y + 44,
               "Sources: Reuters • AP • AFP • Al Jazeera • Guardian • "
               "BBC • Kyodo • USGS • Xinhua",
               "lb", 11, SOFT_INK)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def compose():
    cv = Canvas(PAGE, PAGE, PAPER)
    paint_masthead(cv)

    gap = 10
    colw = (SPAN - 2 * gap) // 3
    for i, item in enumerate(LEADS):
        paint_lead(cv, EDGE + i * (colw + gap), 180, colw, item)

    card_gap = 8
    cardw = (SPAN - 4 * card_gap) // 5
    cardh = 114
    for i, item in enumerate(CARDS):
        col, row = i % 5, i // 5
        paint_card(cv, EDGE + col * (cardw + card_gap),
                   392 + row * (cardh + card_gap), cardw, cardh, item)

    paint_map_panel(cv, EDGE, 634, 300, 324)
    paint_briefs(cv, EDGE + 312, 634, SPAN - 312)
    paint_footer(cv)
    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "entry.png")
    page = compose()
    write_png(target, PAGE, PAGE, page.px)
    print(f"wrote {target}: {PAGE}x{PAGE}")


if __name__ == "__main__":
    main()
