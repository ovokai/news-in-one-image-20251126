#!/usr/bin/env python3
"""The World in One Image -- Thursday 26 November 2026.

A deterministic program that draws a newspaper-front-page style infographic
summarising the world news of Thursday 26 November 2026, and writes it to
entry.png inside the output directory (1024x1024 PNG).

Dependency-free edition: this program uses only the Python standard library,
so it runs in a bare sandbox with no Pillow, no system fonts, no network and
a read-only working directory. All artwork is rasterised by hand into a
frame buffer (rectangles, ellipses, polygons, lines); all text is blitted
from glyph alpha bitmaps embedded in glyphs.py (rendered once, locally,
from DejaVu Sans Bold / Liberation Sans with PIL). PNG encoding is done
with zlib + struct. No randomness, no clock, no network: every run
produces byte-identical output.
"""

import base64
import os
import struct
import zlib
from math import cos, pi, sin, sqrt

# ---------------------------------------------------------------------------
# Canvas and palette
# ---------------------------------------------------------------------------
W = H = 1024
BG = (247, 243, 234)          # warm paper white
INK = (26, 26, 26)            # near-black ink
RED = (179, 32, 42)           # accent red
SEA = (43, 74, 94)            # slate sea
SEA_DARK = (33, 58, 74)
SKY_TOP = (203, 216, 220)
SKY_BOT = (226, 231, 228)
SHIP = (30, 33, 38)           # silhouette
SHIP2 = (52, 57, 63)
FLAME_O = (232, 100, 30)
FLAME_Y = (242, 176, 53)
SMOKE1 = (105, 109, 112)
SMOKE2 = (154, 158, 160)
PANEL_BG = (255, 253, 247)
BORDER = (26, 26, 26)
WAVE = (86, 122, 140)
WHITE = (255, 255, 255)


# ---------------------------------------------------------------------------
# PNG writer (stdlib only)
# ---------------------------------------------------------------------------
def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path, width, height, buf):
    """buf is a bytearray of width*height RGB triples, row-major."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for every scanline
        raw += buf[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------------------
# Frame buffer with hand-rolled rasterisation.
# All coordinates follow PIL conventions: rectangles and ellipse bounding
# boxes are inclusive of both corners.
# ---------------------------------------------------------------------------
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(bytes(bg) * (w * h))

    def fill_rect(self, x0, y0, x1, y1, col):
        x0 = max(0, int(round(x0)))
        y0 = max(0, int(round(y0)))
        x1 = min(self.w - 1, int(round(x1)))
        y1 = min(self.h - 1, int(round(y1)))
        if x1 < x0 or y1 < y0:
            return
        row = bytes(col) * (x1 - x0 + 1)
        n = len(row)
        stride = self.w * 3
        for y in range(y0, y1 + 1):
            i = y * stride + x0 * 3
            self.buf[i:i + n] = row

    def rect_outline(self, x0, y0, x1, y1, col, width):
        self.fill_rect(x0, y0, x1, y0 + width - 1, col)
        self.fill_rect(x0, y1 - width + 1, x1, y1, col)
        self.fill_rect(x0, y0, x0 + width - 1, y1, col)
        self.fill_rect(x1 - width + 1, y0, x1, y1, col)

    def ellipse(self, x0, y0, x1, y1, col):
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        rx = (x1 - x0) / 2.0
        ry = (y1 - y0) / 2.0
        if rx <= 0 or ry <= 0:
            self.fill_rect(x0, y0, x1, y1, col)
            return
        stride = self.w * 3
        row_bytes = bytes(col)
        for y in range(int(y0), int(y1) + 1):
            if y < 0 or y >= self.h:
                continue
            t = (y - cy) / ry
            t2 = t * t
            if t2 > 1.0:
                continue
            dx = rx * sqrt(1.0 - t2)
            xa = max(0, int(round(cx - dx)))
            xb = min(self.w - 1, int(round(cx + dx)))
            if xb < xa:
                continue
            i = y * stride + xa * 3
            self.buf[i:i + (xb - xa + 1) * 3] = row_bytes * (xb - xa + 1)

    def ellipse_outline(self, x0, y0, x1, y1, col, width, inner):
        self.ellipse(x0, y0, x1, y1, col)
        self.ellipse(x0 + width, y0 + width, x1 - width, y1 - width, inner)

    def polygon(self, pts, col):
        pts = [(float(px), float(py)) for px, py in pts]
        ys = [p[1] for p in pts]
        y_lo = max(0, int(min(ys)))
        y_hi = min(self.h - 1, int(max(ys)))
        n = len(pts)
        stride = self.w * 3
        row_bytes = bytes(col)
        for y in range(y_lo, y_hi + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                xa, ya = pts[i]
                xb, yb = pts[(i + 1) % n]
                if ya == yb:
                    continue
                if (ya <= yc < yb) or (yb <= yc < ya):
                    xs.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                xa = max(0, int(round(xs[k])))
                xb = min(self.w - 1, int(round(xs[k + 1])))
                if xb < xa:
                    continue
                i = y * stride + xa * 3
                self.buf[i:i + (xb - xa + 1) * 3] = row_bytes * (xb - xa + 1)

    def line(self, x0, y0, x1, y1, col, width=1):
        if y0 == y1 and width > 1:
            self.fill_rect(min(x0, x1), y0 - width // 2,
                           max(x0, x1), y0 + (width - 1) // 2, col)
            return
        if x0 == x1 and width > 1:
            self.fill_rect(x0 - width // 2, min(y0, y1),
                           x0 + (width - 1) // 2, max(y0, y1), col)
            return
        dist = sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        steps = max(1, int(dist * 2))
        r = width / 2.0
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            self.ellipse(x - r, y - r, x + r, y + r, col)

    def polyline(self, pts, col, width):
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                      col, width)
        r = width / 2.0
        for px, py in pts:
            self.ellipse(px - r, py - r, px + r, py + r, col)

    def rounded_rect(self, x0, y0, x1, y1, r, col):
        # Middle band and side bands are plain rects; corners are quarter
        # discs swept row by row.
        self.fill_rect(x0 + r, y0, x1 - r, y1, col)
        self.fill_rect(x0, y0 + r, x0 + r, y1 - r, col)
        self.fill_rect(x1 - r, y0 + r, x1, y1 - r, col)
        for (ccx, ccy) in [(x0 + r, y0 + r), (x1 - r, y0 + r),
                           (x0 + r, y1 - r), (x1 - r, y1 - r)]:
            self.ellipse(ccx - r, ccy - r, ccx + r, ccy + r, col)
        # The four disc stamps overshoot into the middle; repaint order is
        # fine because every stamp uses the same colour.

    def rounded_rect_outline(self, x0, y0, x1, y1, r, col, width, inner):
        self.rounded_rect(x0, y0, x1, y1, r, col)
        self.rounded_rect(x0 + width, y0 + width, x1 - width, y1 - width,
                          max(0, r - width), inner)


# ---------------------------------------------------------------------------
# Embedded glyphs: alpha bitmaps rendered locally with PIL from DejaVu Sans
# Bold ("db"), Liberation Sans Bold ("lb") and Liberation Sans Regular
# ("lr"), stored in glyphs.py next to this file. Loaded by path (not by
# import) so the program works even when its directory is not on sys.path.
# Each glyph record: [advance, offset_x, offset_y, width, height, bitmap]
# where the bitmap is base85(zlib(raw alpha bytes)) and the offsets place
# the bitmap relative to the text draw point, exactly as PIL drew it.
# ---------------------------------------------------------------------------
def _load_glyph_table():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "glyphs.py")
    ns = {}
    with open(path, "rb") as f:
        exec(compile(f.read(), "glyphs.py", "exec"), ns)
    return ns["GLYPHS"]


GLYPHS = _load_glyph_table()
_bitmap_cache = {}


def _glyph(font_key, size, ch):
    """Return (advance, ox, oy, w, h, alpha_bytes_or_None) for one glyph."""
    rec = GLYPHS[font_key][size][ch]
    adv, ox, oy, w, h, packed = rec
    if not packed:
        return adv, ox, oy, w, h, None
    key = (font_key, size, ch)
    data = _bitmap_cache.get(key)
    if data is None:
        data = zlib.decompress(base64.b85decode(packed.encode("ascii")))
        _bitmap_cache[key] = data
    return adv, ox, oy, w, h, data


def text_width(font_key, size, s):
    table = GLYPHS[font_key][size]
    return sum(table[ch][0] for ch in s)


def _blit_glyph(cv, gx, gy, w, h, data, col):
    """Alpha-blend one glyph bitmap into the frame buffer at (gx, gy)."""
    buf = cv.buf
    width = cv.w
    height = cv.h
    r, g, b = col
    for row in range(h):
        yy = gy + row
        if yy < 0 or yy >= height:
            continue
        src = data[row * w:(row + 1) * w]
        if not src.strip(b"\x00"):
            continue
        base = yy * width * 3
        for i in range(w):
            a = src[i]
            if a:
                xx = gx + i
                if 0 <= xx < width:
                    idx = base + xx * 3
                    if a == 255:
                        buf[idx] = r
                        buf[idx + 1] = g
                        buf[idx + 2] = b
                    else:
                        ia = 255 - a
                        buf[idx] = (r * a + buf[idx] * ia) // 255
                        buf[idx + 1] = (g * a + buf[idx + 1] * ia) // 255
                        buf[idx + 2] = (b * a + buf[idx + 2] * ia) // 255


def draw_text(cv, x, y, s, font_key, size, col):
    """Draw text with the draw point at (x, y), PIL-style (left, ascender)."""
    cx = float(x)
    yi = int(round(y))
    for ch in s:
        adv, ox, oy, w, h, data = _glyph(font_key, size, ch)
        if data is not None:
            _blit_glyph(cv, int(round(cx)) + ox, yi + oy, w, h, data, col)
        cx += adv
    return cx


def draw_centered(cv, cx, y, s, font_key, size, col):
    w = text_width(font_key, size, s)
    draw_text(cv, cx - w / 2.0, y, s, font_key, size, col)


def draw_spaced_centered(cv, cx, y, s, font_key, size, col, tracking):
    """Draw text with manual letter tracking, centred on cx."""
    table = GLYPHS[font_key][size]
    widths = [table[ch][0] for ch in s]
    total = sum(widths) + tracking * (len(s) - 1)
    x = cx - total / 2.0
    for ch, wch in zip(s, widths):
        draw_text(cv, x, y, ch, font_key, size, col)
        x += wch + tracking


def wrap_text(s, font_key, size, max_w):
    """Greedy word wrap by summed glyph advances. Fully deterministic."""
    words = s.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(font_key, size, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Icons (simple silhouettes in a box at x, y of size s)
# ---------------------------------------------------------------------------
def icon_riyadh(cv, x, y, s):
    # tall tower + side building + flame on top
    cv.fill_rect(x + s * 0.34, y + s * 0.28, x + s * 0.62, y + s * 0.98, INK)
    cv.fill_rect(x + s * 0.66, y + s * 0.55, x + s * 0.94, y + s * 0.98, INK)
    cv.fill_rect(x + s * 0.06, y + s * 0.70, x + s * 0.30, y + s * 0.98, INK)
    fx, fy = x + s * 0.48, y + s * 0.30
    cv.polygon([(fx - s * 0.13, fy), (fx, fy - s * 0.30), (fx + s * 0.13, fy)], RED)
    cv.polygon([(fx - s * 0.07, fy), (fx, fy - s * 0.17), (fx + s * 0.07, fy)], FLAME_Y)


def icon_markets(cv, x, y, s):
    # axes + plunging red line with arrowhead
    cv.line(x + s * 0.10, y + s * 0.08, x + s * 0.10, y + s * 0.90, INK, 4)
    cv.line(x + s * 0.10, y + s * 0.90, x + s * 0.95, y + s * 0.90, INK, 4)
    pts = [(x + s * 0.16, y + s * 0.22), (x + s * 0.38, y + s * 0.36),
           (x + s * 0.54, y + s * 0.30), (x + s * 0.86, y + s * 0.78)]
    cv.polyline(pts, RED, 6)
    ax, ay = pts[-1]
    cv.polygon([(ax, ay), (ax - s * 0.16, ay - s * 0.02), (ax - s * 0.03, ay - s * 0.16)], RED)


def icon_ukraine(cv, x, y, s):
    # drone: body + four rotor discs
    cx, cy = x + s * 0.5, y + s * 0.52
    for dx, dy in [(-0.30, -0.26), (0.30, -0.26), (-0.30, 0.26), (0.30, 0.26)]:
        rx, ry = cx + s * dx, cy + s * dy
        cv.line(cx, cy, rx, ry, INK, 4)
        cv.ellipse_outline(rx - s * 0.13, ry - s * 0.06, rx + s * 0.13, ry + s * 0.06,
                           INK, 4, PANEL_BG)
    cv.fill_rect(cx - s * 0.13, cy - s * 0.10, cx + s * 0.13, cy + s * 0.10, INK)
    cv.ellipse(cx - s * 0.05, cy - s * 0.05, cx + s * 0.05, cy + s * 0.05, RED)


def icon_huawei(cv, x, y, s):
    # microchip: body, core, pins
    bx0, by0, bx1, by1 = x + s * 0.24, y + s * 0.24, x + s * 0.76, y + s * 0.76
    for t in (0.34, 0.50, 0.66):
        px, py = x + s * t, y + s * t
        cv.line(px, y + s * 0.06, px, by0, INK, 4)
        cv.line(px, by1, px, y + s * 0.94, INK, 4)
        cv.line(x + s * 0.06, py, bx0, py, INK, 4)
        cv.line(bx1, py, x + s * 0.94, py, INK, 4)
    cv.fill_rect(bx0, by0, bx1, by1, INK)
    cv.fill_rect(x + s * 0.40, y + s * 0.40, x + s * 0.60, y + s * 0.60, RED)


def icon_climate(cv, x, y, s):
    # thermometer with red mercury
    tx = x + s * 0.44
    cv.rounded_rect_outline(tx - s * 0.09, y + s * 0.06, tx + s * 0.09, y + s * 0.68,
                            s * 0.09, INK, 5, PANEL_BG)
    cv.ellipse_outline(tx - s * 0.17, y + s * 0.58, tx + s * 0.17, y + s * 0.92,
                       INK, 5, PANEL_BG)
    cv.fill_rect(tx - s * 0.045, y + s * 0.34, tx + s * 0.045, y + s * 0.70, RED)
    cv.ellipse(tx - s * 0.10, y + s * 0.65, tx + s * 0.10, y + s * 0.85, RED)
    for t in (0.18, 0.32, 0.46):
        cv.line(tx + s * 0.13, y + s * t, tx + s * 0.26, y + s * t, INK, 4)
    # sun behind
    sx, sy = x + s * 0.76, y + s * 0.24
    cv.ellipse(sx - s * 0.11, sy - s * 0.11, sx + s * 0.11, sy + s * 0.11, FLAME_Y)


def icon_space(cv, x, y, s):
    # rocket with red fins and orange flame
    cx = x + s * 0.5
    cv.polygon([(cx, y + s * 0.04), (cx + s * 0.15, y + s * 0.30),
                (cx + s * 0.15, y + s * 0.62), (cx - s * 0.15, y + s * 0.62),
                (cx - s * 0.15, y + s * 0.30)], INK)
    cv.ellipse(cx - s * 0.06, y + s * 0.26, cx + s * 0.06, y + s * 0.38, BG)
    cv.polygon([(cx - s * 0.15, y + s * 0.50), (cx - s * 0.30, y + s * 0.74),
                (cx - s * 0.15, y + s * 0.74)], RED)
    cv.polygon([(cx + s * 0.15, y + s * 0.50), (cx + s * 0.30, y + s * 0.74),
                (cx + s * 0.15, y + s * 0.74)], RED)
    cv.polygon([(cx - s * 0.07, y + s * 0.98), (cx, y + s * 0.74), (cx + s * 0.07, y + s * 0.98)],
               FLAME_O)


def icon_refinery(cv, x, y, s):
    # two storage tanks + a distillation tower with a flare
    cv.fill_rect(x + s * 0.06, y + s * 0.48, x + s * 0.36, y + s * 0.96, INK)
    cv.ellipse(x + s * 0.06, y + s * 0.38, x + s * 0.36, y + s * 0.56, INK)
    cv.fill_rect(x + s * 0.42, y + s * 0.60, x + s * 0.64, y + s * 0.96, INK)
    cv.ellipse(x + s * 0.42, y + s * 0.51, x + s * 0.64, y + s * 0.68, INK)
    cv.fill_rect(x + s * 0.76, y + s * 0.26, x + s * 0.86, y + s * 0.96, INK)
    cv.line(x + s * 0.70, y + s * 0.44, x + s * 0.92, y + s * 0.44, INK, 4)
    cv.line(x + s * 0.70, y + s * 0.62, x + s * 0.92, y + s * 0.62, INK, 4)
    fx, fy = x + s * 0.81, y + s * 0.26
    cv.polygon([(fx - s * 0.08, fy), (fx, fy - s * 0.20), (fx + s * 0.08, fy)], RED)
    cv.polygon([(fx - s * 0.04, fy), (fx, fy - s * 0.11), (fx + s * 0.04, fy)], FLAME_Y)


def icon_missile(cv, x, y, s):
    # diagonal missile climbing to the upper right, flame at the tail
    cv.polygon([(x + s * 0.30, y + s * 0.70), (x + s * 0.62, y + s * 0.14),
                (x + s * 0.72, y + s * 0.10), (x + s * 0.86, y + s * 0.24),
                (x + s * 0.82, y + s * 0.34), (x + s * 0.40, y + s * 0.80)], INK)
    cv.polygon([(x + s * 0.30, y + s * 0.70), (x + s * 0.14, y + s * 0.88),
                (x + s * 0.40, y + s * 0.80)], RED)
    cv.polygon([(x + s * 0.62, y + s * 0.58), (x + s * 0.86, y + s * 0.62),
                (x + s * 0.40, y + s * 0.80)], RED)
    cv.polygon([(x + s * 0.14, y + s * 0.92), (x + s * 0.28, y + s * 0.72),
                (x + s * 0.36, y + s * 0.86)], FLAME_O)
    cv.polygon([(x + s * 0.20, y + s * 0.90), (x + s * 0.29, y + s * 0.76),
                (x + s * 0.33, y + s * 0.86)], FLAME_Y)


def icon_cross(cv, x, y, s):
    # simple latin cross (Vatican / Pope)
    cx = x + s * 0.5
    cv.fill_rect(cx - s * 0.09, y + s * 0.06, cx + s * 0.09, y + s * 0.94, INK)
    cv.fill_rect(cx - s * 0.32, y + s * 0.28, cx + s * 0.32, y + s * 0.45, INK)
    cv.fill_rect(x + s * 0.22, y + s * 0.94, x + s * 0.78, y + s * 0.99, RED)


def icon_bank(cv, x, y, s):
    # central bank: pediment, three columns and a base step
    cv.polygon([(x + s * 0.50, y + s * 0.05), (x + s * 0.95, y + s * 0.30),
                (x + s * 0.05, y + s * 0.30)], INK)
    cv.ellipse(x + s * 0.44, y + s * 0.16, x + s * 0.56, y + s * 0.26, RED)
    cv.fill_rect(x + s * 0.08, y + s * 0.32, x + s * 0.92, y + s * 0.38, INK)
    for t in (0.16, 0.44, 0.72):
        cv.fill_rect(x + s * t, y + s * 0.42, x + s * (t + 0.12), y + s * 0.78, INK)
    cv.fill_rect(x + s * 0.08, y + s * 0.82, x + s * 0.92, y + s * 0.88, INK)
    cv.fill_rect(x + s * 0.04, y + s * 0.92, x + s * 0.96, y + s * 0.97, INK)


def icon_rain(cv, x, y, s):
    # monsoon cloud with slanted rain streaks
    cv.ellipse(x + s * 0.16, y + s * 0.16, x + s * 0.60, y + s * 0.50, INK)
    cv.ellipse(x + s * 0.42, y + s * 0.06, x + s * 0.88, y + s * 0.50, INK)
    cv.fill_rect(x + s * 0.16, y + s * 0.34, x + s * 0.88, y + s * 0.50, INK)
    for t in (0.26, 0.50, 0.74):
        cv.line(x + s * t, y + s * 0.60, x + s * (t - 0.09), y + s * 0.88, WAVE, 5)
    cv.line(x + s * 0.10, y + s * 0.95, x + s * 0.90, y + s * 0.95, SEA, 4)


def icon_dove(cv, x, y, s):
    # dove of peace: body, raised wing, tail and a red beak
    cv.polygon([(x + s * 0.20, y + s * 0.56), (x + s * 0.02, y + s * 0.44),
                (x + s * 0.05, y + s * 0.74), (x + s * 0.24, y + s * 0.72)], INK)
    cv.ellipse(x + s * 0.16, y + s * 0.40, x + s * 0.78, y + s * 0.78, INK)
    cv.polygon([(x + s * 0.32, y + s * 0.48), (x + s * 0.14, y + s * 0.12),
                (x + s * 0.54, y + s * 0.38)], INK)
    cv.ellipse(x + s * 0.60, y + s * 0.20, x + s * 0.88, y + s * 0.48, INK)
    cv.polygon([(x + s * 0.85, y + s * 0.30), (x + s * 0.99, y + s * 0.37),
                (x + s * 0.85, y + s * 0.42)], RED)
    cv.ellipse(x + s * 0.70, y + s * 0.28, x + s * 0.76, y + s * 0.34, PANEL_BG)


ICONS = {
    "OIL": icon_refinery,
    "SEOUL": icon_markets,
    "TOKYO": icon_markets,
    "WASHINGTON": icon_bank,
    "RIYADH": icon_riyadh,
    "RUSSIA": icon_ukraine,
    "KYIV": icon_missile,
    "HUAWEI": icon_huawei,
    "CLIMATE": icon_climate,
    "SPACE": icon_space,
    "GAZA": icon_dove,
    "INDIA": icon_rain,
}

PANELS = [
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
# Scene: Strait of Hormuz
# ---------------------------------------------------------------------------
def tanker(cv, x, y, scale, hull_col, burning):
    """Draw a tanker silhouette with its keel line at y."""
    hull_w, hull_h = 340 * scale, 34 * scale
    # hull (bow to the right)
    cv.polygon([(x, y - hull_h), (x + hull_w * 0.86, y - hull_h),
                (x + hull_w, y - hull_h * 0.35), (x + hull_w * 0.94, y),
                (x + hull_w * 0.08, y), (x, y - hull_h * 0.3)], hull_col)
    # deck line and cargo hatches
    cv.fill_rect(x + hull_w * 0.10, y - hull_h - 8 * scale,
                 x + hull_w * 0.62, y - hull_h, hull_col)
    # bridge / superstructure at the stern (left)
    cv.fill_rect(x + hull_w * 0.06, y - hull_h - 52 * scale,
                 x + hull_w * 0.20, y - hull_h - 8 * scale, hull_col)
    cv.fill_rect(x + hull_w * 0.09, y - hull_h - 66 * scale,
                 x + hull_w * 0.17, y - hull_h - 52 * scale, hull_col)
    # mast amidships
    cv.line(x + hull_w * 0.45, y - hull_h - 8 * scale,
            x + hull_w * 0.45, y - hull_h - 58 * scale,
            hull_col, max(2, int(4 * scale)))
    if burning:
        fx = x + hull_w * 0.38
        fy = y - hull_h - 6 * scale
        # smoke plume (kept inside the scene box: max rise 195 units)
        for (sx, sy, r, col) in [(0.46, -118, 30, SMOKE2), (0.52, -140, 38, SMOKE1),
                                 (0.60, -160, 46, SMOKE2), (0.70, -178, 52, SMOKE1),
                                 (0.82, -195, 58, SMOKE2)]:
            cx, cy = x + hull_w * sx, y + sy * scale
            cv.ellipse(cx - r * scale, cy - r * 0.62 * scale,
                       cx + r * scale, cy + r * 0.62 * scale, col)
        # flames: layered teardrops
        for (dx, hgt, wid, col) in [(0.0, 120, 30, RED), (26, 150, 34, FLAME_O),
                                    (54, 105, 26, RED), (30, 92, 22, FLAME_Y),
                                    (8, 70, 18, FLAME_Y)]:
            cx = fx + dx * scale
            cv.polygon([(cx - wid * scale, fy), (cx, fy - hgt * scale),
                        (cx + wid * scale, fy)], col)
            cv.ellipse(cx - wid * scale, fy - wid * 0.5 * scale,
                       cx + wid * scale, fy + wid * 0.5 * scale, col)


def draw_headline_scene(cv):
    x0, y0, x1, y1 = 36, 206, 988, 356
    # sky: two flat bands (deterministic gradient feel)
    cv.fill_rect(x0, y0, x1, 308, SKY_BOT)
    cv.fill_rect(x0, y0, x1, 272, SKY_TOP)
    # sea
    cv.fill_rect(x0, 308, x1, y1, SEA)
    cv.fill_rect(x0, 308, x1, 314, SEA_DARK)
    for i, wy in enumerate((324, 340)):
        off = 60 if i % 2 else 0
        for wx in range(x0 + 40 + off, x1 - 60, 170):
            cv.line(wx, wy, wx + 52, wy, WAVE, 3)
    # The strait is shut: three tankers ride at anchor, none burning --
    # a near one on the left, a small distant one mid-frame and a second
    # large one held on the right.
    tanker(cv, 385, 320, 0.30, SHIP2, burning=False)
    tanker(cv, 100, 342, 0.55, SHIP, burning=False)
    tanker(cv, 615, 338, 0.48, SHIP2, burning=False)
    # Dashed red turn-back route over the right-hand tanker: the arc a
    # diverted ship steams, ending in an arrowhead pointing back west.
    cx, cy, r = 712, 330, 56
    pts = []
    for i in range(25):
        th = pi * (0.12 + 0.76 * i / 24)
        pts.append((cx + r * cos(th), cy - r * sin(th)))
    for i in range(0, len(pts) - 1, 2):
        cv.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], RED, 4)
    ax, ay = pts[-1]
    cv.polygon([(ax, ay), (ax + 17, ay - 3), (ax + 7, ay + 13)], RED)
    # A line of red closure buoys across the channel in front of them.
    for bx in range(150, 950, 88):
        cv.ellipse(bx - 8, 343, bx + 8, 355, RED)
        cv.fill_rect(bx - 8, 347, bx + 8, 350, WHITE)
    cv.rect_outline(x0, y0, x1, y1, BORDER, 3)


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
def draw_panel(cv, x, y, w, h, region, title):
    cv.fill_rect(x, y, x + w, y + h, PANEL_BG)
    cv.rect_outline(x, y, x + w, y + h, BORDER, 2)
    cv.fill_rect(x, y, x + 5, y + h, RED)
    pad = 12
    icon_s = 34
    ICONS[region](cv, x + pad + 2, y + 9, icon_s)
    draw_text(cv, x + pad + icon_s + 10, y + 15, region, "lb", 21, RED)
    # Title: start at 22px; shrink only as far as needed so the full
    # title fits the panel (no clipped words), never below 19px.
    size = 22
    while size > 19:
        lines = wrap_text(title, "lb", size, w - pad * 2 - 4)
        if len(lines) <= 4:
            break
        size -= 1
    ty = y + 52
    for ln in lines[:4]:
        draw_text(cv, x + pad + 2, ty, ln, "lb", size, INK)
        ty += size + 4


# ---------------------------------------------------------------------------
# Main composition
# ---------------------------------------------------------------------------
def build():
    cv = Canvas(W, H, BG)
    cx = W // 2

    # ---- Masthead -------------------------------------------------------
    cv.fill_rect(36, 14, 988, 16, INK)
    draw_spaced_centered(cv, cx, 24, "THE WORLD IN ONE IMAGE", "lb", 26, RED, 10)
    draw_centered(cv, cx, 54, "THURSDAY", "db", 80, INK)
    draw_centered(cv, cx, 130, "26 NOVEMBER 2026", "db", 70, INK)
    cv.fill_rect(36, 196, 988, 200, INK)

    # ---- Headline scene + caption --------------------------------------
    draw_headline_scene(cv)
    cap_y = 364
    cv.fill_rect(36, cap_y, 44, cap_y + 72, RED)
    draw_text(cv, 60, cap_y + 2, "STRAIT OF HORMUZ", "db", 44, INK)
    draw_text(cv, 60, cap_y + 52,
              "Iran closes the strait to all shipping; tankers turn back",
              "lb", 23, INK)

    # ---- Twelve panels ---------------------------------------------------
    panel_w, panel_h, gap = 232, 162, 8
    top = 442
    for i, (region, title) in enumerate(PANELS):
        col, row = i % 4, i // 4
        px = 36 + col * (panel_w + gap)
        py = top + row * (panel_h + gap)
        draw_panel(cv, px, py, panel_w, panel_h, region, title)

    # ---- Bottom banner ---------------------------------------------------
    by0, by1 = 954, 1010
    cv.fill_rect(36, by0, 988, by1, RED)
    banner_lines = [
        "ALSO TODAY: Shinkansen derails after a quake off Honshu",
        "Pope offers the Vatican for Gaza talks \u2022 "
        "Airlines reroute Gulf flights",
    ]
    size = 20
    while size > 12 and any(text_width("lb", size, s) > 936 for s in banner_lines):
        size -= 1
    draw_centered(cv, cx, by0 + 5, banner_lines[0], "lb", size, WHITE)
    draw_centered(cv, cx, by0 + 30, banner_lines[1], "lb", size, WHITE)

    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    cv = build()
    write_png(out_path, W, H, cv.buf)
    print(f"wrote {out_path}: {W}x{H}")


if __name__ == "__main__":
    main()
