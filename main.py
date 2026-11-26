#!/usr/bin/env python3
"""The World in One Image -- Thursday 26 November 2026.

Draws a broadsheet-style front page that sums up the day's world news and
saves it as entry.png (1024 x 1024) in the output folder.

The program is self-contained: standard library only, so it runs in a
bare sandbox (no Pillow, no system fonts, no network, read-only working
directory). Pictures are painted into an in-memory pixel grid with
hand-written scanline routines; lettering comes from glyph bitmaps
bundled in glyphs.py; the PNG file is assembled with zlib and struct.
There is no randomness and no clock access, so repeated runs produce
exactly the same bytes.
"""

import base64
import os
import struct
import zlib
from math import cos, pi, sin, sqrt

# ---------------------------------------------------------------------------
# Geometry of the page and the ink colours used across it
# ---------------------------------------------------------------------------
PAGE_W = 1024
PAGE_H = 1024
EDGE = 36                       # left/right margin of the printed area
RIGHT = PAGE_W - EDGE           # 988

PAPER = (247, 243, 234)         # warm off-white page
JET = (26, 26, 26)              # body ink
CRIMSON = (179, 32, 42)         # accent red
DEEP_SEA = (43, 74, 94)
DEEP_SEA_DK = (33, 58, 74)
SKY_HIGH = (203, 216, 220)
SKY_LOW = (226, 231, 228)
HULL_DARK = (30, 33, 38)
HULL_MID = (52, 57, 63)
EMBER = (232, 100, 30)
GOLD = (242, 176, 53)
CARD = (255, 253, 247)          # panel fill
RIPPLE = (86, 122, 140)
PURE_WHITE = (255, 255, 255)


# ---------------------------------------------------------------------------
# PNG serialisation (zlib + struct, filter 0 on every row)
# ---------------------------------------------------------------------------
def _signed_chunk(kind, body):
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def save_png(filename, width, height, pixels):
    """pixels: bytearray holding width*height RGB triples, row by row."""
    rows = []
    stride = width * 3
    for y in range(height):
        rows.append(b"\x00")
        rows.append(bytes(pixels[y * stride:(y + 1) * stride]))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n"
            + _signed_chunk(b"IHDR", header)
            + _signed_chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
            + _signed_chunk(b"IEND", b""))
    with open(filename, "wb") as fh:
        fh.write(blob)


# ---------------------------------------------------------------------------
# Pixel surface with scanline painters.
# Box coordinates follow the usual image convention: both corners count
# as painted (inclusive), matching how the page was laid out.
# ---------------------------------------------------------------------------
class Surface:
    def __init__(self, width, height, base):
        self.width = width
        self.height = height
        self.px = bytearray(bytes(base) * (width * height))

    # -- low-level run painter -------------------------------------------
    def _run(self, y, xa, xb, colour):
        if y < 0 or y >= self.height:
            return
        xa = max(0, xa)
        xb = min(self.width - 1, xb)
        if xb < xa:
            return
        start = (y * self.width + xa) * 3
        self.px[start:start + (xb - xa + 1) * 3] = bytes(colour) * (xb - xa + 1)

    # -- rectangles --------------------------------------------------------
    def rect(self, xa, ya, xb, yb, colour):
        xa, ya = int(round(xa)), int(round(ya))
        xb, yb = int(round(xb)), int(round(yb))
        for y in range(max(0, ya), min(self.height - 1, yb) + 1):
            self._run(y, xa, xb, colour)

    def frame(self, xa, ya, xb, yb, colour, thick):
        self.rect(xa, ya, xb, ya + thick - 1, colour)
        self.rect(xa, yb - thick + 1, xb, yb, colour)
        self.rect(xa, ya, xa + thick - 1, yb, colour)
        self.rect(xb - thick + 1, ya, xb, yb, colour)

    # -- ellipses ----------------------------------------------------------
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
            self._run(y, int(round(cx - half)), int(round(cx + half)), colour)

    def oval_ring(self, xa, ya, xb, yb, colour, thick, inside):
        self.oval(xa, ya, xb, yb, colour)
        self.oval(xa + thick, ya + thick, xb - thick, yb - thick, inside)

    # -- polygons ------------------------------------------------------------
    def shape(self, points, colour):
        pts = [(float(a), float(b)) for a, b in points]
        top = max(0, int(min(b for _, b in pts)))
        bottom = min(self.height - 1, int(max(b for _, b in pts)))
        n = len(pts)
        for y in range(top, bottom + 1):
            scan = y + 0.5
            crossings = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if ay == by:
                    continue
                if (ay <= scan < by) or (by <= scan < ay):
                    crossings.append(ax + (scan - ay) * (bx - ax) / (by - ay))
            crossings.sort()
            for k in range(0, len(crossings) - 1, 2):
                self._run(y, int(round(crossings[k])),
                          int(round(crossings[k + 1])), colour)

    # -- strokes -------------------------------------------------------------
    def stroke(self, xa, ya, xb, yb, colour, thick=1):
        # Axis-aligned thick strokes are just rectangles.
        if ya == yb and thick > 1:
            self.rect(min(xa, xb), ya - thick // 2,
                      max(xa, xb), ya + (thick - 1) // 2, colour)
            return
        if xa == xb and thick > 1:
            self.rect(xa - thick // 2, min(ya, yb),
                      xa + (thick - 1) // 2, max(ya, yb), colour)
            return
        length = sqrt((xb - xa) ** 2 + (yb - ya) ** 2)
        steps = max(1, int(length * 2))
        rad = thick / 2.0
        for i in range(steps + 1):
            t = i / steps
            x, y = xa + (xb - xa) * t, ya + (yb - ya) * t
            self.oval(x - rad, y - rad, x + rad, y + rad, colour)

    def stroke_path(self, points, colour, thick):
        for i in range(len(points) - 1):
            self.stroke(points[i][0], points[i][1],
                        points[i + 1][0], points[i + 1][1], colour, thick)
        rad = thick / 2.0
        for x, y in points:
            self.oval(x - rad, y - rad, x + rad, y + rad, colour)

    # -- rounded rectangles ----------------------------------------------------
    def roundrect(self, xa, ya, xb, yb, rad, colour):
        self.rect(xa + rad, ya, xb - rad, yb, colour)
        self.rect(xa, ya + rad, xa + rad, yb - rad, colour)
        self.rect(xb - rad, ya + rad, xb, yb - rad, colour)
        for ccx, ccy in ((xa + rad, ya + rad), (xb - rad, ya + rad),
                         (xa + rad, yb - rad), (xb - rad, yb - rad)):
            self.oval(ccx - rad, ccy - rad, ccx + rad, ccy + rad, colour)

    def roundrect_frame(self, xa, ya, xb, yb, rad, colour, thick, inside):
        self.roundrect(xa, ya, xb, yb, rad, colour)
        self.roundrect(xa + thick, ya + thick, xb - thick, yb - thick,
                       max(0, rad - thick), inside)


# ---------------------------------------------------------------------------
# Lettering. glyphs.py (kept beside this file) holds alpha bitmaps that
# were rendered once with PIL from DejaVu Sans Bold ("db"), Liberation
# Sans Bold ("lb") and Liberation Sans Regular ("lr"). It is read by path
# rather than imported, so the program works even when its folder is not
# on sys.path. A glyph record is [advance, off_x, off_y, w, h, bitmap]
# with the bitmap base85(zlib(raw alpha)) and the offsets relative to the
# PIL draw point (left edge, top of ascender).
# ---------------------------------------------------------------------------
def _read_glyph_book():
    folder = os.path.dirname(os.path.abspath(__file__))
    namespace = {}
    with open(os.path.join(folder, "glyphs.py"), "rb") as fh:
        exec(compile(fh.read(), "glyphs.py", "exec"), namespace)
    return namespace["GLYPHS"]


GLYPH_BOOK = _read_glyph_book()
_unpacked = {}


def _letter(face, size, ch):
    """(advance, off_x, off_y, w, h, alpha bytes or None) for one letter."""
    adv, ox, oy, w, h, packed = GLYPH_BOOK[face][size][ch]
    if not packed:
        return adv, ox, oy, w, h, None
    key = (face, size, ch)
    if key not in _unpacked:
        _unpacked[key] = zlib.decompress(base64.b85decode(packed.encode("ascii")))
    return adv, ox, oy, w, h, _unpacked[key]


def measure(face, size, text):
    table = GLYPH_BOOK[face][size]
    return sum(table[ch][0] for ch in text)


def _stamp(surf, gx, gy, w, h, alpha, colour):
    """Alpha-blend a single glyph bitmap into the surface at (gx, gy)."""
    red, green, blue = colour
    for row in range(h):
        yy = gy + row
        if yy < 0 or yy >= surf.height:
            continue
        line = alpha[row * w:(row + 1) * w]
        if not line.strip(b"\x00"):
            continue
        base = yy * surf.width * 3
        for i, a in enumerate(line):
            if not a:
                continue
            xx = gx + i
            if not (0 <= xx < surf.width):
                continue
            at = base + xx * 3
            if a == 255:
                surf.px[at] = red
                surf.px[at + 1] = green
                surf.px[at + 2] = blue
            else:
                keep = 255 - a
                surf.px[at] = (red * a + surf.px[at] * keep) // 255
                surf.px[at + 1] = (green * a + surf.px[at + 1] * keep) // 255
                surf.px[at + 2] = (blue * a + surf.px[at + 2] * keep) // 255


def paint_text(surf, x, y, text, face, size, colour):
    """Draw text; (x, y) is the PIL-style draw point (left, ascender)."""
    pen = float(x)
    top = int(round(y))
    for ch in text:
        adv, ox, oy, w, h, alpha = _letter(face, size, ch)
        if alpha is not None:
            _stamp(surf, int(round(pen)) + ox, top + oy, w, h, alpha, colour)
        pen += adv
    return pen


def paint_centered(surf, centre, y, text, face, size, colour):
    paint_text(surf, centre - measure(face, size, text) / 2.0, y,
               text, face, size, colour)


def paint_tracked(surf, centre, y, text, face, size, colour, tracking):
    """Centred text with extra space inserted between the letters."""
    table = GLYPH_BOOK[face][size]
    advances = [table[ch][0] for ch in text]
    pen = centre - (sum(advances) + tracking * (len(text) - 1)) / 2.0
    for ch, adv in zip(text, advances):
        paint_text(surf, pen, y, ch, face, size, colour)
        pen += adv + tracking


def fold(text, face, size, limit):
    """Greedy word wrap using glyph advances; fully deterministic."""
    lines, current = [], ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if measure(face, size, trial) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Panel icons: small silhouettes drawn inside a box whose top-left corner
# is (x, y) and whose side is s. All proportions are fractions of s.
# ---------------------------------------------------------------------------
def mark_tower(sv, x, y, s):
    # Office tower under attack, flame bursting from its roof.
    sv.rect(x + 0.34 * s, y + 0.28 * s, x + 0.62 * s, y + 0.98 * s, JET)
    sv.rect(x + 0.66 * s, y + 0.55 * s, x + 0.94 * s, y + 0.98 * s, JET)
    sv.rect(x + 0.06 * s, y + 0.70 * s, x + 0.30 * s, y + 0.98 * s, JET)
    fx, fy = x + 0.48 * s, y + 0.30 * s
    sv.shape([(fx - 0.13 * s, fy), (fx, fy - 0.30 * s), (fx + 0.13 * s, fy)], CRIMSON)
    sv.shape([(fx - 0.07 * s, fy), (fx, fy - 0.17 * s), (fx + 0.07 * s, fy)], GOLD)


def mark_chart(sv, x, y, s):
    # Axes and a red line diving to the lower right with an arrowhead.
    sv.stroke(x + 0.10 * s, y + 0.08 * s, x + 0.10 * s, y + 0.90 * s, JET, 4)
    sv.stroke(x + 0.10 * s, y + 0.90 * s, x + 0.95 * s, y + 0.90 * s, JET, 4)
    path = [(x + 0.16 * s, y + 0.22 * s), (x + 0.38 * s, y + 0.36 * s),
            (x + 0.54 * s, y + 0.30 * s), (x + 0.86 * s, y + 0.78 * s)]
    sv.stroke_path(path, CRIMSON, 6)
    tip_x, tip_y = path[-1]
    sv.shape([(tip_x, tip_y), (tip_x - 0.16 * s, tip_y - 0.02 * s),
              (tip_x - 0.03 * s, tip_y - 0.16 * s)], CRIMSON)


def mark_drone(sv, x, y, s):
    # Quadcopter seen from the front: four rotor rings around a body.
    cx, cy = x + 0.5 * s, y + 0.52 * s
    for dx, dy in ((-0.30, -0.26), (0.30, -0.26), (-0.30, 0.26), (0.30, 0.26)):
        rx, ry = cx + dx * s, cy + dy * s
        sv.stroke(cx, cy, rx, ry, JET, 4)
        sv.oval_ring(rx - 0.13 * s, ry - 0.06 * s, rx + 0.13 * s, ry + 0.06 * s,
                     JET, 4, CARD)
    sv.rect(cx - 0.13 * s, cy - 0.10 * s, cx + 0.13 * s, cy + 0.10 * s, JET)
    sv.oval(cx - 0.05 * s, cy - 0.05 * s, cx + 0.05 * s, cy + 0.05 * s, CRIMSON)


def mark_chip(sv, x, y, s):
    # Microchip: square body, red core, pins on all four sides.
    bx0, by0, bx1, by1 = x + 0.24 * s, y + 0.24 * s, x + 0.76 * s, y + 0.76 * s
    for t in (0.34, 0.50, 0.66):
        sv.stroke(x + t * s, y + 0.06 * s, x + t * s, by0, JET, 4)
        sv.stroke(x + t * s, by1, x + t * s, y + 0.94 * s, JET, 4)
        sv.stroke(x + 0.06 * s, y + t * s, bx0, y + t * s, JET, 4)
        sv.stroke(bx1, y + t * s, x + 0.94 * s, y + t * s, JET, 4)
    sv.rect(bx0, by0, bx1, by1, JET)
    sv.rect(x + 0.40 * s, y + 0.40 * s, x + 0.60 * s, y + 0.60 * s, CRIMSON)


def mark_thermometer(sv, x, y, s):
    # Thermometer with red mercury, tick marks, and a small sun behind.
    tx = x + 0.44 * s
    sv.roundrect_frame(tx - 0.09 * s, y + 0.06 * s, tx + 0.09 * s, y + 0.68 * s,
                       0.09 * s, JET, 5, CARD)
    sv.oval_ring(tx - 0.17 * s, y + 0.58 * s, tx + 0.17 * s, y + 0.92 * s,
                 JET, 5, CARD)
    sv.rect(tx - 0.045 * s, y + 0.34 * s, tx + 0.045 * s, y + 0.70 * s, CRIMSON)
    sv.oval(tx - 0.10 * s, y + 0.65 * s, tx + 0.10 * s, y + 0.85 * s, CRIMSON)
    for t in (0.18, 0.32, 0.46):
        sv.stroke(tx + 0.13 * s, y + t * s, tx + 0.26 * s, y + t * s, JET, 4)
    sx, sy = x + 0.76 * s, y + 0.24 * s
    sv.oval(sx - 0.11 * s, sy - 0.11 * s, sx + 0.11 * s, sy + 0.11 * s, GOLD)


def mark_rocket(sv, x, y, s):
    # Rocket with a porthole, red fins and an orange exhaust flame.
    cx = x + 0.5 * s
    sv.shape([(cx, y + 0.04 * s), (cx + 0.15 * s, y + 0.30 * s),
              (cx + 0.15 * s, y + 0.62 * s), (cx - 0.15 * s, y + 0.62 * s),
              (cx - 0.15 * s, y + 0.30 * s)], JET)
    sv.oval(cx - 0.06 * s, y + 0.26 * s, cx + 0.06 * s, y + 0.38 * s, PAPER)
    sv.shape([(cx - 0.15 * s, y + 0.50 * s), (cx - 0.30 * s, y + 0.74 * s),
              (cx - 0.15 * s, y + 0.74 * s)], CRIMSON)
    sv.shape([(cx + 0.15 * s, y + 0.50 * s), (cx + 0.30 * s, y + 0.74 * s),
              (cx + 0.15 * s, y + 0.74 * s)], CRIMSON)
    sv.shape([(cx - 0.07 * s, y + 0.98 * s), (cx, y + 0.74 * s),
              (cx + 0.07 * s, y + 0.98 * s)], EMBER)


def mark_refinery(sv, x, y, s):
    # Two storage tanks and a fractionating column with a flare on top.
    sv.rect(x + 0.06 * s, y + 0.48 * s, x + 0.36 * s, y + 0.96 * s, JET)
    sv.oval(x + 0.06 * s, y + 0.38 * s, x + 0.36 * s, y + 0.56 * s, JET)
    sv.rect(x + 0.42 * s, y + 0.60 * s, x + 0.64 * s, y + 0.96 * s, JET)
    sv.oval(x + 0.42 * s, y + 0.51 * s, x + 0.64 * s, y + 0.68 * s, JET)
    sv.rect(x + 0.76 * s, y + 0.26 * s, x + 0.86 * s, y + 0.96 * s, JET)
    sv.stroke(x + 0.70 * s, y + 0.44 * s, x + 0.92 * s, y + 0.44 * s, JET, 4)
    sv.stroke(x + 0.70 * s, y + 0.62 * s, x + 0.92 * s, y + 0.62 * s, JET, 4)
    fx, fy = x + 0.81 * s, y + 0.26 * s
    sv.shape([(fx - 0.08 * s, fy), (fx, fy - 0.20 * s), (fx + 0.08 * s, fy)], CRIMSON)
    sv.shape([(fx - 0.04 * s, fy), (fx, fy - 0.11 * s), (fx + 0.04 * s, fy)], GOLD)


def mark_missile(sv, x, y, s):
    # Missile climbing diagonally up-right, fins and flame at the tail.
    sv.shape([(x + 0.30 * s, y + 0.70 * s), (x + 0.62 * s, y + 0.14 * s),
              (x + 0.72 * s, y + 0.10 * s), (x + 0.86 * s, y + 0.24 * s),
              (x + 0.82 * s, y + 0.34 * s), (x + 0.40 * s, y + 0.80 * s)], JET)
    sv.shape([(x + 0.30 * s, y + 0.70 * s), (x + 0.14 * s, y + 0.88 * s),
              (x + 0.40 * s, y + 0.80 * s)], CRIMSON)
    sv.shape([(x + 0.62 * s, y + 0.58 * s), (x + 0.86 * s, y + 0.62 * s),
              (x + 0.40 * s, y + 0.80 * s)], CRIMSON)
    sv.shape([(x + 0.14 * s, y + 0.92 * s), (x + 0.28 * s, y + 0.72 * s),
              (x + 0.36 * s, y + 0.86 * s)], EMBER)
    sv.shape([(x + 0.20 * s, y + 0.90 * s), (x + 0.29 * s, y + 0.76 * s),
              (x + 0.33 * s, y + 0.86 * s)], GOLD)


def mark_cross(sv, x, y, s):
    # Latin cross on a red base step (the Vatican panel).
    cx = x + 0.5 * s
    sv.rect(cx - 0.09 * s, y + 0.06 * s, cx + 0.09 * s, y + 0.94 * s, JET)
    sv.rect(cx - 0.32 * s, y + 0.28 * s, cx + 0.32 * s, y + 0.45 * s, JET)
    sv.rect(x + 0.22 * s, y + 0.94 * s, x + 0.78 * s, y + 0.99 * s, CRIMSON)


def mark_bank(sv, x, y, s):
    # Central bank facade: pediment, three columns, steps.
    sv.shape([(x + 0.50 * s, y + 0.05 * s), (x + 0.95 * s, y + 0.30 * s),
              (x + 0.05 * s, y + 0.30 * s)], JET)
    sv.oval(x + 0.44 * s, y + 0.16 * s, x + 0.56 * s, y + 0.26 * s, CRIMSON)
    sv.rect(x + 0.08 * s, y + 0.32 * s, x + 0.92 * s, y + 0.38 * s, JET)
    for t in (0.16, 0.44, 0.72):
        sv.rect(x + t * s, y + 0.42 * s, x + (t + 0.12) * s, y + 0.78 * s, JET)
    sv.rect(x + 0.08 * s, y + 0.82 * s, x + 0.92 * s, y + 0.88 * s, JET)
    sv.rect(x + 0.04 * s, y + 0.92 * s, x + 0.96 * s, y + 0.97 * s, JET)


def mark_rain(sv, x, y, s):
    # Monsoon cloud shedding slanted rain over a water line.
    sv.oval(x + 0.16 * s, y + 0.16 * s, x + 0.60 * s, y + 0.50 * s, JET)
    sv.oval(x + 0.42 * s, y + 0.06 * s, x + 0.88 * s, y + 0.50 * s, JET)
    sv.rect(x + 0.16 * s, y + 0.34 * s, x + 0.88 * s, y + 0.50 * s, JET)
    for t in (0.26, 0.50, 0.74):
        sv.stroke(x + t * s, y + 0.60 * s, x + (t - 0.09) * s, y + 0.88 * s,
                  RIPPLE, 5)
    sv.stroke(x + 0.10 * s, y + 0.95 * s, x + 0.90 * s, y + 0.95 * s, DEEP_SEA, 4)


def mark_dove(sv, x, y, s):
    # Dove of peace: tail, body, raised wing, head and a red beak.
    sv.shape([(x + 0.20 * s, y + 0.56 * s), (x + 0.02 * s, y + 0.44 * s),
              (x + 0.05 * s, y + 0.74 * s), (x + 0.24 * s, y + 0.72 * s)], JET)
    sv.oval(x + 0.16 * s, y + 0.40 * s, x + 0.78 * s, y + 0.78 * s, JET)
    sv.shape([(x + 0.32 * s, y + 0.48 * s), (x + 0.14 * s, y + 0.12 * s),
              (x + 0.54 * s, y + 0.38 * s)], JET)
    sv.oval(x + 0.60 * s, y + 0.20 * s, x + 0.88 * s, y + 0.48 * s, JET)
    sv.shape([(x + 0.85 * s, y + 0.30 * s), (x + 0.99 * s, y + 0.37 * s),
              (x + 0.85 * s, y + 0.42 * s)], CRIMSON)
    sv.oval(x + 0.70 * s, y + 0.28 * s, x + 0.76 * s, y + 0.34 * s, CARD)


MARKS = {
    "OIL": mark_refinery,
    "SEOUL": mark_chart,
    "TOKYO": mark_chart,
    "WASHINGTON": mark_bank,
    "RIYADH": mark_tower,
    "RUSSIA": mark_drone,
    "KYIV": mark_missile,
    "HUAWEI": mark_chip,
    "CLIMATE": mark_thermometer,
    "SPACE": mark_rocket,
    "GAZA": mark_dove,
    "INDIA": mark_rain,
}

# The twelve panel stories: (region label, one-line summary).
STORIES = [
    ("OIL", "Brent crude leaps +14% in a day as the strait stays shut"),
    ("SEOUL", "KOSPI falls for a second day as the oil shock spreads"),
    ("TOKYO", "Nikkei slides \u22123.1%; the yen sinks to a record low"),
    ("WASHINGTON", "Fed holds an emergency meeting on the oil shock"),
    ("RIYADH", "Probe points to Houthi drones in the tower strike"),
    ("RUSSIA", "Russia condemns Ukraine strikes on its oil refineries"),
    ("KYIV", "Kyiv blacked out after an overnight missile barrage"),
    ("HUAWEI", "Huawei fraud trial opens in a New York courtroom"),
    ("CLIMATE", "Protests erupt after COP31 ends with no deal"),
    ("SPACE", "Shenzhou-24 crew makes its first spacewalk"),
    ("GAZA", "Ceasefire talks restart in Cairo; strikes pause"),
    ("INDIA", "Monsoon floods swamp Mumbai; trains halted"),
]


# ---------------------------------------------------------------------------
# Headline picture: the Strait of Hormuz, closed. Three tankers sit at
# anchor; a dashed red arc shows the turn-back route and a line of red
# buoys bars the channel.
# ---------------------------------------------------------------------------
def oil_tanker(sv, x, keel, scale, tone):
    """Tanker silhouette; `keel` is the y of its waterline."""
    beam = 340 * scale
    hull_h = 34 * scale
    # Hull, bow pointing right.
    sv.shape([(x, keel - hull_h), (x + 0.86 * beam, keel - hull_h),
              (x + beam, keel - 0.35 * hull_h), (x + 0.94 * beam, keel),
              (x + 0.08 * beam, keel), (x, keel - 0.3 * hull_h)], tone)
    # Cargo deck strip.
    sv.rect(x + 0.10 * beam, keel - hull_h - 8 * scale,
            x + 0.62 * beam, keel - hull_h, tone)
    # Stern castle and its top house.
    sv.rect(x + 0.06 * beam, keel - hull_h - 52 * scale,
            x + 0.20 * beam, keel - hull_h - 8 * scale, tone)
    sv.rect(x + 0.09 * beam, keel - hull_h - 66 * scale,
            x + 0.17 * beam, keel - hull_h - 52 * scale, tone)
    # Midships mast.
    sv.stroke(x + 0.45 * beam, keel - hull_h - 8 * scale,
              x + 0.45 * beam, keel - hull_h - 58 * scale,
              tone, max(2, int(4 * scale)))


def strait_picture(sv):
    top, bottom = 206, 356
    horizon = 308
    # Sky in two flat bands, then the sea with a dark waterline.
    sv.rect(EDGE, top, RIGHT, horizon, SKY_LOW)
    sv.rect(EDGE, top, RIGHT, 272, SKY_HIGH)
    sv.rect(EDGE, horizon, RIGHT, bottom, DEEP_SEA)
    sv.rect(EDGE, horizon, RIGHT, 314, DEEP_SEA_DK)
    # Short wave strokes in two rows.
    for row, wy in enumerate((324, 340)):
        offset = 60 if row % 2 else 0
        for wx in range(EDGE + 40 + offset, RIGHT - 60, 170):
            sv.stroke(wx, wy, wx + 52, wy, RIPPLE, 3)
    # The anchored fleet: a small distant ship, a big near one, and a
    # second large one held back on the right.
    oil_tanker(sv, 385, 320, 0.30, HULL_MID)
    oil_tanker(sv, 100, 342, 0.55, HULL_DARK)
    oil_tanker(sv, 615, 338, 0.48, HULL_MID)
    # Dashed red arc over the right-hand ship: the course a diverted
    # tanker steams, arrowhead swinging back towards the west.
    cx, cy, radius = 712, 330, 56
    arc = []
    for i in range(25):
        theta = pi * (0.12 + 0.76 * i / 24)
        arc.append((cx + radius * cos(theta), cy - radius * sin(theta)))
    for i in range(0, len(arc) - 1, 2):
        sv.stroke(arc[i][0], arc[i][1], arc[i + 1][0], arc[i + 1][1],
                  CRIMSON, 4)
    head_x, head_y = arc[-1]
    sv.shape([(head_x, head_y), (head_x + 17, head_y - 3),
              (head_x + 7, head_y + 13)], CRIMSON)
    # Closure buoys strung across the channel.
    for bx in range(150, 950, 88):
        sv.oval(bx - 8, 343, bx + 8, 355, CRIMSON)
        sv.rect(bx - 8, 347, bx + 8, 350, PURE_WHITE)
    sv.frame(EDGE, top, RIGHT, bottom, JET, 3)


# ---------------------------------------------------------------------------
# One news panel: red spine, icon, region label, wrapped summary text.
# ---------------------------------------------------------------------------
def news_panel(sv, x, y, w, h, region, summary):
    sv.rect(x, y, x + w, y + h, CARD)
    sv.frame(x, y, x + w, y + h, JET, 2)
    sv.rect(x, y, x + 5, y + h, CRIMSON)
    inset = 12
    mark_size = 34
    MARKS[region](sv, x + inset + 2, y + 9, mark_size)
    paint_text(sv, x + inset + mark_size + 10, y + 15, region, "lb", 21, CRIMSON)
    # Summary starts at 22pt and shrinks (never under 19pt) until the
    # whole text fits in four lines.
    size = 22
    lines = fold(summary, "lb", size, w - inset * 2 - 4)
    while len(lines) > 4 and size > 19:
        size -= 1
        lines = fold(summary, "lb", size, w - inset * 2 - 4)
    ty = y + 52
    for line in lines[:4]:
        paint_text(sv, x + inset + 2, ty, line, "lb", size, JET)
        ty += size + 4


# ---------------------------------------------------------------------------
# Whole page: masthead, headline picture with caption, panel grid,
# and the red "also today" banner along the bottom.
# ---------------------------------------------------------------------------
def compose_page():
    sv = Surface(PAGE_W, PAGE_H, PAPER)
    middle = PAGE_W // 2

    # Masthead.
    sv.rect(EDGE, 14, RIGHT, 16, JET)
    paint_tracked(sv, middle, 24, "THE WORLD IN ONE IMAGE", "lb", 26,
                  CRIMSON, 10)
    paint_centered(sv, middle, 54, "THURSDAY", "db", 80, JET)
    paint_centered(sv, middle, 130, "26 NOVEMBER 2026", "db", 70, JET)
    sv.rect(EDGE, 196, RIGHT, 200, JET)

    # Headline picture and its caption.
    strait_picture(sv)
    cap = 364
    sv.rect(EDGE, cap, 44, cap + 72, CRIMSON)
    paint_text(sv, 60, cap + 2, "STRAIT OF HORMUZ", "db", 44, JET)
    paint_text(sv, 60, cap + 52,
               "Iran closes the strait to all shipping; tankers turn back",
               "lb", 23, JET)

    # Twelve panels in a 4 x 3 grid.
    cell_w, cell_h, gap = 232, 162, 8
    grid_top = 442
    for index, (region, summary) in enumerate(STORIES):
        col, row = index % 4, index // 4
        news_panel(sv, EDGE + col * (cell_w + gap),
                   grid_top + row * (cell_h + gap),
                   cell_w, cell_h, region, summary)

    # Bottom banner.
    band_top, band_bot = 954, 1010
    sv.rect(EDGE, band_top, RIGHT, band_bot, CRIMSON)
    briefs = [
        "ALSO TODAY: Shinkansen derails after a quake off Honshu",
        "Pope offers the Vatican for Gaza talks \u2022 "
        "Airlines reroute Gulf flights",
    ]
    size = 20
    while size > 12 and any(measure("lb", size, s) > 936 for s in briefs):
        size -= 1
    paint_centered(sv, middle, band_top + 5, briefs[0], "lb", size, PURE_WHITE)
    paint_centered(sv, middle, band_top + 30, briefs[1], "lb", size, PURE_WHITE)

    return sv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "entry.png")
    page = compose_page()
    save_png(target, PAGE_W, PAGE_H, page.px)
    print(f"wrote {target}: {PAGE_W}x{PAGE_H}")


if __name__ == "__main__":
    main()
