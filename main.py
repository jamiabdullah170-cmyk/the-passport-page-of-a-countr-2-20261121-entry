#!/usr/bin/env python3
"""The Passport Page of a Country That Isn't There — make.fun entry.

Pure Python 3.13 stdlib (no Pillow, no network). Draws one invented
passport spread (data page + visas/stamps page) for the fictional
Republic of Kalvera and writes it to /output/entry.png (1024x724,
PNG, under 1 MiB). Fully deterministic: two runs are byte-identical.

Country: Republic of Kalvera — a small lighthouse republic on a
northern coast. Capital / port: Vesna. Bearer: Elena Mara Voss,
keeper of the Vesna Light. Every date is consistent: passport issued
02 JUN 2023, expires 01 JUN 2033; every stamp falls in 2024-2025,
after issue and before expiry.
"""

import math
import os
import struct
import zlib

# ---------------------------------------------------------------- canvas
W, H = 1024, 724          # final pixels (<= 1024 x 1024)
SS = 2                    # supersampling factor for anti-aliasing
SW, SH = W * SS, H * SS   # working buffer size


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


PAPER = rgb("#f6f1e2")
PAPER_DK = rgb("#e9e1c9")
INK = rgb("#1d2f45")        # navy ink
TEAL = rgb("#0f4c5c")
TEAL_LT = rgb("#2e6b78")
GOLD = rgb("#a8842f")
GOLD_LT = rgb("#c9a959")
BURG = rgb("#7a2e3a")
GREY = rgb("#5c6470")
FAINT = rgb("#8b8574")
PHOTO_BG = rgb("#cfe0db")
SKIN = rgb("#d9a986")
SKIN_DK = rgb("#c08a63")
HAIR = rgb("#3a2a1e")
JACKET = rgb("#274b5f")
STAMP_BLUE = rgb("#33509e")
STAMP_PURPLE = rgb("#6b3f8f")
STAMP_RED = rgb("#8a3b2e")
STAMP_GREEN = rgb("#2e6b4f")
STAMP_BLUE_LT = rgb("#7d90c4")
WHITE = rgb("#fdfcf6")


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)

    def fill(self, color):
        b = bytes(color)
        self.buf[:] = b * (self.w * self.h)

    def _span(self, y, x0, x1, color):
        """Fill pixels [x0, x1) on row y (clipped)."""
        if y < 0 or y >= self.h:
            return
        x0 = max(0, int(math.floor(x0)))
        x1 = min(self.w, int(math.ceil(x1)))
        if x1 <= x0:
            return
        i = (y * self.w + x0) * 3
        self.buf[i:(y * self.w + x1) * 3] = bytes(color) * (x1 - x0)

    def rect(self, x0, y0, x1, y1, color):
        x0 = int(round(x0)); y0 = int(round(y0))
        x1 = int(round(x1)); y1 = int(round(y1))
        for y in range(max(0, y0), min(self.h, y1)):
            self._span(y, x0, x1, color)

    def poly(self, pts, color):
        """Scanline fill of a polygon (even-odd), pts = [(x, y), ...]."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x0, yy0 = pts[i]
                x1, yy1 = pts[(i + 1) % n]
                if yy0 == yy1:
                    continue
                if (yy0 <= yc < yy1) or (yy1 <= yc < yy0):
                    xs.append(x0 + (yc - yy0) * (x1 - x0) / (yy1 - yy0))
            if len(xs) < 2:
                continue
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self._span(y, xs[k], xs[k + 1], color)

    def disc(self, cx, cy, r, color):
        r2 = r * r
        y0 = max(0, int(math.floor(cy - r)))
        y1 = min(self.h - 1, int(math.ceil(cy + r)))
        for y in range(y0, y1 + 1):
            dy = (y + 0.5) - cy
            dx = math.sqrt(max(0.0, r2 - dy * dy))
            self._span(y, cx - dx, cx + dx, color)

    def ring(self, cx, cy, r0, r1, color):
        """Filled annulus r0 <= d < r1."""
        y0 = max(0, int(math.floor(cy - r1)))
        y1 = min(self.h - 1, int(math.ceil(cy + r1)))
        for y in range(y0, y1 + 1):
            dy = (y + 0.5) - cy
            d_out = math.sqrt(max(0.0, r1 * r1 - dy * dy))
            if abs(dy) < r0:
                d_in = math.sqrt(max(0.0, r0 * r0 - dy * dy))
                self._span(y, cx - d_out, cx - d_in, color)
                self._span(y, cx + d_in, cx + d_out, color)
            else:
                self._span(y, cx - d_out, cx + d_out, color)

    def line(self, x0, y0, x1, y1, width, color):
        """Thick line with round caps."""
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            self.disc(x0, y0, width / 2.0, color)
            return
        nx, ny = -dy / ln * width / 2.0, dx / ln * width / 2.0
        self.poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                   (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], color)
        self.disc(x0, y0, width / 2.0, color)
        self.disc(x1, y1, width / 2.0, color)

    def ellipse(self, cx, cy, rx, ry, color):
        y0 = max(0, int(math.floor(cy - ry)))
        y1 = min(self.h - 1, int(math.ceil(cy + ry)))
        for y in range(y0, y1 + 1):
            dy = ((y + 0.5) - cy) / ry
            dx = rx * math.sqrt(max(0.0, 1.0 - dy * dy))
            self._span(y, cx - dx, cx + dx, color)

    def downsample(self):
        """Box-average SSxSS blocks -> final W x H RGB bytes."""
        out = bytearray(W * H * 3)
        inv = 1.0 / (SS * SS)
        for y in range(H):
            for x in range(W):
                r = g = b = 0
                for dy in range(SS):
                    base = ((y * SS + dy) * SW + x * SS) * 3
                    for dx in range(SS):
                        i = base + dx * 3
                        r += self.buf[i]; g += self.buf[i + 1]; b += self.buf[i + 2]
                o = (y * W + x) * 3
                out[o] = int(r * inv); out[o + 1] = int(g * inv); out[o + 2] = int(b * inv)
        return bytes(out)


# ---------------------------------------------------------------- PNG
def _chunk(typ, data):
    c = struct.pack(">I", len(data)) + typ + data
    return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def write_png(path, rgb_bytes, w, h):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filter: none
        raw += rgb_bytes[y * stride:(y + 1) * stride]
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)

# ---------------------------------------------------------------- font
# Single-stroke vector font, drawn from scratch for this entry.
# Grid: x in [0, 12], y in [0, 16] (0 = top, 14 = baseline).
# Each glyph: (advance, [strokes]); a stroke is a list of (x, y).
FONT = {
    "A": (13, [[(1, 14), (6, 1), (11, 14)], [(4, 9), (8, 9)]]),
    "B": (12, [[(2, 1), (2, 14)], [(2, 1), (8, 1), (10, 3), (10, 6), (8, 8), (2, 8)],
                [(2, 8), (8, 8), (10, 10), (10, 12), (8, 14), (2, 14)]]),
    "C": (12, [[(10, 4), (8, 1), (4, 1), (2, 3), (2, 11), (4, 14), (8, 14), (10, 12)]]),
    "D": (12, [[(2, 1), (2, 14), (8, 14), (10, 12), (10, 3), (8, 1), (2, 1)]]),
    "E": (11, [[(10, 1), (2, 1), (2, 14), (10, 14)], [(2, 7), (8, 7)]]),
    "F": (11, [[(2, 14), (2, 1), (10, 1)], [(2, 7), (8, 7)]]),
    "G": (12, [[(10, 4), (8, 1), (4, 1), (2, 3), (2, 11), (4, 14), (8, 14),
                (10, 12), (10, 8), (7, 8)]]),
    "H": (12, [[(2, 1), (2, 14)], [(10, 1), (10, 14)], [(2, 7), (10, 7)]]),
    "I": (9, [[(5, 1), (5, 14)], [(2, 1), (8, 1)], [(2, 14), (8, 14)]]),
    "J": (11, [[(3, 1), (9, 1)], [(7, 1), (7, 12), (5, 14), (3, 13)]]),
    "K": (12, [[(2, 1), (2, 14)], [(9, 1), (2, 8)], [(4, 6), (10, 14)]]),
    "L": (11, [[(2, 1), (2, 14), (10, 14)]]),
    "M": (13, [[(2, 14), (2, 1), (6, 8), (10, 1), (10, 14)]]),
    "N": (12, [[(2, 14), (2, 1), (10, 14), (10, 1)]]),
    "O": (12, [[(4, 1), (8, 1), (10, 3), (10, 11), (8, 14), (4, 14),
                (2, 11), (2, 3), (4, 1)]]),
    "P": (12, [[(2, 14), (2, 1), (8, 1), (10, 3), (10, 6), (8, 8), (2, 8)]]),
    "Q": (12, [[(4, 1), (8, 1), (10, 3), (10, 11), (8, 14), (4, 14),
                (2, 11), (2, 3), (4, 1)], [(7, 11), (11, 15)]]),
    "R": (12, [[(2, 14), (2, 1), (8, 1), (10, 3), (10, 6), (8, 8), (2, 8)],
                [(5, 8), (10, 14)]]),
    "S": (12, [[(10, 4), (8, 1), (4, 1), (2, 3), (2, 6), (4, 8), (8, 9),
                (10, 11), (10, 13), (8, 14), (4, 14), (2, 13)]]),
    "T": (12, [[(1, 1), (11, 1)], [(6, 1), (6, 14)]]),
    "U": (12, [[(2, 1), (2, 11), (4, 14), (8, 14), (10, 11), (10, 1)]]),
    "V": (12, [[(1, 1), (6, 14), (11, 1)]]),
    "W": (13, [[(1, 1), (3, 14), (6, 8), (9, 14), (11, 1)]]),
    "X": (12, [[(2, 1), (10, 14)], [(10, 1), (2, 14)]]),
    "Y": (12, [[(2, 1), (6, 8), (10, 1)], [(6, 8), (6, 14)]]),
    "Z": (12, [[(2, 1), (10, 1), (2, 14), (10, 14)]]),
    "0": (12, [[(4, 1), (8, 1), (10, 3), (10, 11), (8, 14), (4, 14),
                (2, 11), (2, 3), (4, 1)]]),
    "1": (9, [[(5, 3), (7, 1), (7, 14)], [(3, 14), (10, 14)]]),
    "2": (12, [[(2, 4), (3, 1), (8, 1), (10, 3), (10, 6), (2, 14), (10, 14)]]),
    "3": (12, [[(2, 3), (4, 1), (8, 1), (10, 3), (10, 6), (8, 8), (10, 10),
                (10, 12), (8, 14), (4, 14), (2, 13)]]),
    "4": (12, [[(9, 1), (9, 14)], [(2, 10), (10, 10)], [(9, 1), (2, 10)]]),
    "5": (12, [[(10, 1), (2, 1), (2, 7), (8, 7), (10, 9), (10, 12),
                (8, 14), (2, 14)]]),
    "6": (12, [[(10, 4), (8, 1), (4, 1), (2, 3), (2, 12), (4, 14), (8, 14),
                (10, 12), (10, 9), (8, 7), (4, 7), (2, 9)]]),
    "7": (12, [[(2, 1), (10, 1), (6, 14)]]),
    "8": (12, [[(4, 1), (8, 1), (10, 3), (10, 6), (8, 8), (4, 8), (2, 6),
                (2, 3), (4, 1)],
                [(4, 8), (8, 8), (10, 10), (10, 12), (8, 14), (4, 14),
                 (2, 12), (2, 10), (4, 8)]]),
    "9": (12, [[(2, 4), (4, 1), (8, 1), (10, 3), (10, 9), (8, 11), (4, 11),
                (2, 9), (2, 4)], [(10, 4), (10, 12), (8, 14), (5, 14)]]),
    " ": (6, []),
    ".": (6, [[(5, 13), (5, 13)]]),
    ",": (6, [[(5, 12), (5, 13)], [(5, 13), (3, 15)]]),
    "-": (12, [[(2, 8), (10, 8)]]),
    "/": (12, [[(9, 1), (3, 14)]]),
    ":": (6, [[(5, 5), (5, 5)], [(5, 11), (5, 11)]]),
    "(": (8, [[(7, 1), (4, 3), (4, 11), (7, 14)]]),
    ")": (8, [[(1, 1), (4, 3), (4, 11), (1, 14)]]),
    "<": (12, [[(10, 1), (3, 7), (10, 14)]]),
    ">": (12, [[(2, 1), (9, 7), (2, 14)]]),
    "'": (6, [[(5, 1), (4, 5)]]),
    "+": (12, [[(6, 3), (6, 11)], [(2, 7), (10, 7)]]),
    "=": (12, [[(2, 5), (10, 5)], [(2, 10), (10, 10)]]),
    "!": (6, [[(5, 1), (5, 10)], [(5, 13), (5, 13)]]),
    "?": (12, [[(3, 4), (4, 1), (8, 1), (10, 3), (10, 5), (8, 7), (6, 8),
                (6, 10)], [(6, 13), (6, 13)]]),
    "%": (13, [[(10, 1), (2, 14)], [(3, 4), (3, 4)], [(9, 11), (9, 11)]]),
    "*": (12, [[(6, 1), (6, 13)], [(1, 4), (11, 10)], [(11, 4), (1, 10)]]),
    "\u2022": (8, []),  # bullet: drawn as a filled disc
    "\u00b7": (6, [[(5, 7), (5, 7)]]),
}


def _draw_stroke(c, stroke, transform, width, color):
    pts = [transform(x, y) for (x, y) in stroke]
    for i in range(len(pts) - 1):
        c.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], width, color)
    if len(pts) == 1:
        c.disc(pts[0][0], pts[0][1], width / 2.0, color)


def text_width(text, cap, spacing=0.0):
    """Width of text in final px (cap = cap height in final px)."""
    scale = cap / 14.0
    w = 0.0
    for ch in text:
        adv, _ = FONT.get(ch, FONT["?"])
        w += adv * scale + spacing
    return w - spacing if text else 0.0


def draw_text(c, x, y_top, text, cap, color, weight=0.11, spacing=0.0,
              align="left"):
    """Draw text; (x, y_top) is the top-left of the cap-height box
    (final-px coordinates; internally scaled by SS)."""
    scale = cap / 14.0 * SS
    pen = max(1.0, cap * weight * SS)
    tw = text_width(text, cap, spacing)
    if align == "center":
        x -= tw / 2.0
    elif align == "right":
        x -= tw
    cx = x * SS
    cy = y_top * SS
    for ch in text:
        if ch == "\u2022":
            c.disc(cx + 4 * scale, cy + 7 * scale, 1.7 * scale, color)
            cx += 8 * scale
            continue
        adv, strokes = FONT.get(ch, FONT["?"])
        for stroke in strokes:
            _draw_stroke(c, stroke,
                         lambda gx, gy, cx=cx, cy=cy, s=scale: (cx + gx * s, cy + gy * s),
                         pen, color)
        cx += (adv * scale + spacing * SS)
    return tw


def draw_text_arc(c, cx, cy, radius, text, cap, color, start_deg, end_deg,
                  weight=0.11, flip=False):
    """Draw text along a circle arc, centred on the arc span.
    Angles in degrees, 0 = east, increasing clockwise (screen coords)."""
    scale = cap / 14.0 * SS
    pen = max(1.0, cap * weight * SS)
    tw_units = sum(FONT.get(ch, FONT["?"])[0] for ch in text)
    total = math.radians(end_deg - start_deg)
    # arc length in glyph units -> distribute characters evenly
    n = len(text)
    for i, ch in enumerate(text):
        frac = (i + 0.5) / n
        ang = math.radians(start_deg + frac * (end_deg - start_deg))
        # glyph centre sits on the circle; glyph "up" points outward
        px = cx * SS + math.cos(ang) * radius * SS
        py = cy * SS + math.sin(ang) * radius * SS
        rot = ang + math.pi / 2.0  # glyph +y axis points outward
        if flip:
            rot += math.pi
        adv, strokes = FONT.get(ch, FONT["?"])
        ox, oy = 6.0, 7.0  # glyph centre in grid units
        for stroke in strokes:
            def tr(gx, gy, px=px, py=py, s=scale, r=rot, ox=ox, oy=oy):
                lx, ly = (gx - ox) * s, (gy - oy) * s
                return (px + lx * math.cos(r) - ly * math.sin(r),
                        py + lx * math.sin(r) + ly * math.cos(r))
            _draw_stroke(c, stroke, tr, pen, color)
        if ch == "\u2022":
            c.disc(px, py, 1.7 * scale, color)

# ---------------------------------------------------------------- MRZ
_MRZ_VAL = {}
for _i in range(10):
    _MRZ_VAL[str(_i)] = _i
for _i, _ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _MRZ_VAL[_ch] = 10 + _i
_MRZ_VAL["<"] = 0


def mrz_check(s):
    total = 0
    for i, ch in enumerate(s):
        total += _MRZ_VAL[ch] * (7, 3, 1)[i % 3]
    return str(total % 10)


def mrz_lines():
    line1 = ("P<KLV" + "VOSS<<ELENA<MARA").ljust(44, "<")
    doc = "KLV482913"
    dob = "880314"
    exp = "330601"
    pers = "<" * 14
    body = (doc + mrz_check(doc) + "KLV" + dob + mrz_check(dob) + "F"
            + exp + mrz_check(exp) + pers + mrz_check(pers))
    line2 = body + mrz_check(body)
    assert len(line1) == 44 and len(line2) == 44
    return line1, line2


# ---------------------------------------------------------------- helpers
def s(v):
    return v * SS


def frame(c, x0, y0, x1, y1, color, width=1.0, inset=0.0):
    c.line(s(x0 + inset), s(y0 + inset), s(x1 - inset), s(y0 + inset), width * SS, color)
    c.line(s(x1 - inset), s(y0 + inset), s(x1 - inset), s(y1 - inset), width * SS, color)
    c.line(s(x1 - inset), s(y1 - inset), s(x0 + inset), s(y1 - inset), width * SS, color)
    c.line(s(x0 + inset), s(y1 - inset), s(x0 + inset), s(y0 + inset), width * SS, color)


def guilloche(c, x0, y0, x1, y1, color, step=9.0, amp=2.5):
    """Faint wavy horizontal lines across a region."""
    y = y0 + 4.0
    while y < y1 - 2:
        pts = []
        x = x0
        while x <= x1:
            pts.append((s(x), s(y + amp * math.sin((x - x0) / 26.0))))
            x += 4.0
        for i in range(len(pts) - 1):
            c.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.7 * SS, color)
        y += step


def coat_of_arms(c, cx, cy, size, color):
    """Shield with a lighthouse and a star above it."""
    u = size / 44.0  # unit
    cx, cy = s(cx), s(cy)
    # star above shield
    star = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = 4.2 * u if i % 2 == 0 else 1.8 * u
        star.append((cx + r * math.cos(ang), cy - 26 * u + r * math.sin(ang)))
    c.poly(star, color)
    # shield outline
    pts = [(cx - 15 * u, cy - 18 * u), (cx + 15 * u, cy - 18 * u),
           (cx + 15 * u, cy + 4 * u), (cx, cy + 20 * u), (cx - 15 * u, cy + 4 * u)]
    c.poly(pts, color)
    c.poly([(cx - 12 * u, cy - 15 * u), (cx + 12 * u, cy - 15 * u),
            (cx + 12 * u, cy + 3 * u), (cx, cy + 16 * u), (cx - 12 * u, cy + 3 * u)],
           PAPER)
    # lighthouse: tower + light rays + waves
    tx = cx
    c.poly([(tx - 3.5 * u, cy + 12 * u), (tx - 2.2 * u, cy - 6 * u),
            (tx + 2.2 * u, cy - 6 * u), (tx + 3.5 * u, cy + 12 * u)], color)
    c.rect(tx - 3.2 * u, cy - 9.5 * u, tx + 3.2 * u, cy - 6.5 * u, color)
    c.line(tx - 6 * u, cy - 8 * u, tx - 11 * u, cy - 11 * u, 1.4 * u, color)
    c.line(tx + 6 * u, cy - 8 * u, tx + 11 * u, cy - 11 * u, 1.4 * u, color)
    c.line(tx - 6 * u, cy - 8 * u, tx - 11 * u, cy - 5 * u, 1.4 * u, color)
    c.line(tx + 6 * u, cy - 8 * u, tx + 11 * u, cy - 5 * u, 1.4 * u, color)
    for k, wy in enumerate((14 * u, 17 * u)):
        c.line(cx - 10 * u, cy + wy, cx + 10 * u, cy + wy, 1.2 * u,
               color if k == 0 else TEAL_LT)


def draw_portrait(c, x0, y0, x1, y1):
    """Stylised passport photograph: woman, dark hair in a bun,
    teal jacket, facing the camera. Flat vector style."""
    cx = (x0 + x1) / 2.0
    w = x1 - x0
    u = w / 150.0
    # background: pale teal with faint arcs (kept inside the photo)
    c.rect(s(x0), s(y0), s(x1), s(y1), PHOTO_BG)
    for r in (24, 44, 64, 82):
        c.ring(s(cx), s(y0 + 95 * u), r * u, r * u + 0.8 * SS, rgb("#b8d2cb"))
    # shoulders / jacket
    c.poly([(s(x0 + 6), s(y1)), (s(cx - 36 * u), s(y0 + 150 * u)),
            (s(cx + 36 * u), s(y0 + 150 * u)), (s(x1 - 6), s(y1))], JACKET)
    # white collar
    c.poly([(s(cx - 13 * u), s(y0 + 150 * u)), (s(cx), s(y0 + 178 * u)),
            (s(cx + 13 * u), s(y0 + 150 * u)), (s(cx + 7 * u), s(y0 + 144 * u)),
            (s(cx), s(y0 + 158 * u)), (s(cx - 7 * u), s(y0 + 144 * u))], WHITE)
    # gold lighthouse pin on the lapel
    c.disc(s(cx - 24 * u), s(y0 + 170 * u), 4.5 * u, GOLD)
    c.disc(s(cx - 24 * u), s(y0 + 170 * u), 2.5 * u, PAPER)
    # neck
    c.rect(s(cx - 7.5 * u), s(y0 + 130 * u), s(cx + 7.5 * u), s(y0 + 152 * u), SKIN)
    # head
    c.ellipse(s(cx), s(y0 + 90 * u), 32 * u, 38 * u, SKIN)
    # cheek shading
    c.ellipse(s(cx - 17 * u), s(y0 + 102 * u), 9 * u, 12 * u, rgb("#e0b58f"))
    c.ellipse(s(cx + 17 * u), s(y0 + 102 * u), 9 * u, 12 * u, rgb("#e0b58f"))
    # hair: neat bob with a forehead hairline, sides down to the jaw
    c.poly([(s(cx - 32 * u), s(y0 + 108 * u)), (s(cx - 31 * u), s(y0 + 70 * u)),
            (s(cx - 20 * u), s(y0 + 52 * u)), (s(cx), s(y0 + 48 * u)),
            (s(cx + 20 * u), s(y0 + 52 * u)), (s(cx + 31 * u), s(y0 + 70 * u)),
            (s(cx + 32 * u), s(y0 + 108 * u)), (s(cx + 26 * u), s(y0 + 80 * u)),
            (s(cx + 14 * u), s(y0 + 61 * u)), (s(cx), s(y0 + 59 * u)),
            (s(cx - 14 * u), s(y0 + 61 * u)), (s(cx - 26 * u), s(y0 + 80 * u))], HAIR)
    # ears
    c.ellipse(s(cx - 31 * u), s(y0 + 94 * u), 4 * u, 7 * u, SKIN)
    c.ellipse(s(cx + 31 * u), s(y0 + 94 * u), 4 * u, 7 * u, SKIN)
    # eyebrows
    c.line(s(cx - 21 * u), s(y0 + 80 * u), s(cx - 9 * u), s(y0 + 78 * u), 2.2 * u, HAIR)
    c.line(s(cx + 9 * u), s(y0 + 78 * u), s(cx + 21 * u), s(y0 + 80 * u), 2.2 * u, HAIR)
    # eyes
    for ex in (-15 * u, 15 * u):
        c.ellipse(s(cx + ex), s(y0 + 89 * u), 5.5 * u, 3.2 * u, WHITE)
        c.disc(s(cx + ex), s(y0 + 89 * u), 2.6 * u, rgb("#2b2620"))
    # nose
    c.line(s(cx), s(y0 + 92 * u), s(cx - 2 * u), s(y0 + 104 * u), 1.6 * u, SKIN_DK)
    c.line(s(cx - 2 * u), s(y0 + 104 * u), s(cx + 2 * u), s(y0 + 105 * u), 1.6 * u, SKIN_DK)
    # lips
    c.poly([(s(cx - 7 * u), s(y0 + 115 * u)), (s(cx), s(y0 + 113 * u)),
            (s(cx + 7 * u), s(y0 + 115 * u)), (s(cx), s(y0 + 119 * u))],
           rgb("#a85a4e"))


def signature(c, x, y, width, color):
    """Flowing holder's signature (Elena M. Voss): one gentle wave
    with a capital loop at the start, plus an underline."""
    u = width / 120.0
    # capital loop
    c.ellipse(s(x + 8 * u), s(y + 5 * u), 6 * u, 5 * u, color)
    # main flowing stroke
    pts = []
    for i in range(0, 121, 6):
        pts.append((i, 8 + 2.5 * math.sin(i / 11.0)))
    for i in range(len(pts) - 1):
        c.line(s(x + pts[i][0] * u), s(y + pts[i][1] * u),
               s(x + pts[i + 1][0] * u), s(y + pts[i + 1][1] * u),
               1.6 * SS, color)
    # underline
    c.line(s(x + 4 * u), s(y + 14 * u), s(x + 118 * u), s(y + 14 * u), 1.1 * SS, color)

# ---------------------------------------------------------------- stamps
def circular_stamp(c, cx, cy, r, color, top_text, bottom_text, centre,
                   date):
    """Round border-control stamp: text on the ring, centre lines."""
    cap = max(7.5, min(10.5, r * 0.16))
    c.ring(s(cx), s(cy), (r - 2.5) * SS, r * SS, color)
    c.ring(s(cx), s(cy), (r - 11.5) * SS, (r - 10.5) * SS, color)
    # top arc text reads left-to-right over the top; bottom arc reads
    # left-to-right along the bottom (angles decrease, glyphs flipped)
    draw_text_arc(c, cx, cy, r - 6.5, top_text, cap, color, 205, 335)
    draw_text_arc(c, cx, cy, r - 6.5, bottom_text, cap, color, 155, 25, flip=True)
    # centre: small star, word, date (caps shrink on small stamps)
    c.disc(s(cx), s(cy - r * 0.38), 2.2 * SS, color)
    cc = 12 if r >= 55 else 10.5
    dc = 11.5 if r >= 55 else 9.5
    draw_text(c, cx, cy - r * 0.28, centre, cc, color, weight=0.13, align="center")
    c.line(s(cx - r * 0.42), s(cy + r * 0.02), s(cx + r * 0.42), s(cy + r * 0.02),
           1.0 * SS, color)
    draw_text(c, cx, cy + r * 0.10, date, dc, color, weight=0.13, align="center")


def _rot(px, py, cx, cy, ang):
    dx, dy = px - cx, py - cy
    ca, sa = math.cos(ang), math.sin(ang)
    return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)


def rect_stamp(c, x0, y0, x1, y1, deg, color, lines, small=None):
    """Rectangular entry/exit stamp, slightly rotated like a real one."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ang = math.radians(deg)
    corners = [_rot(x0, y0, cx, cy, ang), _rot(x1, y0, cx, cy, ang),
               _rot(x1, y1, cx, cy, ang), _rot(x0, y1, cx, cy, ang)]
    c.poly([(s(px), s(py)) for px, py in corners], color)
    inner = [_rot(x0 + 4, y0 + 4, cx, cy, ang), _rot(x1 - 4, y0 + 4, cx, cy, ang),
             _rot(x1 - 4, y1 - 4, cx, cy, ang), _rot(x0 + 4, y1 - 4, cx, cy, ang)]
    c.poly([(s(px), s(py)) for px, py in inner], PAPER)
    # text lines, rotated as a block around the centre
    n = len(lines)
    for i, (txt, cap) in enumerate(lines):
        ly = y0 + 10 + i * (cap + 7)
        tw = text_width(txt, cap)
        tx, ty = cx - tw / 2.0, ly
        # rotate the text origin around the centre, then draw unrotated
        # (small angles: acceptable, keeps glyphs upright like a stamp)
        rx, ry = _rot(tx, ty, cx, cy, ang)
        draw_text(c, rx, ry, txt, cap, color, weight=0.13)
    if small:
        rx, ry = _rot(cx - text_width(small, 7.5) / 2.0, y1 - 14, cx, cy, ang)
        draw_text(c, rx, ry, small, 7.5, color, weight=0.12)


def fee_stamp(c, x0, y0, x1, y1, deg, color):
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ang = math.radians(deg)
    corners = [_rot(x0, y0, cx, cy, ang), _rot(x1, y0, cx, cy, ang),
               _rot(x1, y1, cx, cy, ang), _rot(x0, y1, cx, cy, ang)]
    c.poly([(s(px), s(py)) for px, py in corners], color)
    inner = [_rot(x0 + 3, y0 + 3, cx, cy, ang), _rot(x1 - 3, y0 + 3, cx, cy, ang),
             _rot(x1 - 3, y1 - 3, cx, cy, ang), _rot(x0 + 3, y1 - 3, cx, cy, ang)]
    c.poly([(s(px), s(py)) for px, py in inner], PAPER)
    for i, (txt, cap) in enumerate([("FEE PAID", 13), ("40 KRD", 13)]):
        ly = y0 + 9 + i * 19
        tw = text_width(txt, cap)
        rx, ry = _rot(cx - tw / 2.0, ly, cx, cy, ang)
        draw_text(c, rx, ry, txt, cap, color, weight=0.14)


# ---------------------------------------------------------------- pages
def field(c, x, y, label, value, cap=15, label_cap=8.5, color=INK, vcolor=INK):
    draw_text(c, x, y, label, label_cap, GREY, weight=0.13, spacing=0.4)
    draw_text(c, x, y + 11, value, cap, vcolor, weight=0.13)


def draw_left_page(c):
    x0, x1, y0, y1 = 14, 510, 14, 710
    guilloche(c, x0 + 10, y0 + 150, x1 - 10, y1 - 90, rgb("#e3dcc2"), step=11)
    frame(c, x0 + 6, y0 + 6, x1 - 6, y1 - 6, GOLD, width=1.0)
    # header: arms + country
    coat_of_arms(c, 262, 62, 56, TEAL)
    draw_text(c, 262, 96, "REPUBLIC OF KALVERA", 23, INK, weight=0.14,
              spacing=1.2, align="center")
    draw_text(c, 262, 124, "PASSPORT  \u2022  PASSEPORT  \u2022  PASAPORTE", 10.5,
              TEAL, weight=0.13, spacing=0.8, align="center")
    c.line(s(60), s(142), s(464), s(142), 1.2 * SS, GOLD)
    # photograph
    frame(c, 34, 152, 184, 342, INK, width=2.0)
    draw_portrait(c, 38, 156, 180, 338)
    # signature under the photo
    signature(c, 40, 352, 138, rgb("#2b3a6e"))
    c.line(s(40), s(372), s(178), s(372), 1.0 * SS, INK)
    draw_text(c, 109, 378, "HOLDER'S SIGNATURE", 8, GREY, weight=0.13,
              align="center")
    # data fields
    field(c, 204, 156, "TYPE", "P", cap=15)
    field(c, 282, 156, "CODE", "KLV", cap=15)
    field(c, 360, 156, "PASSPORT NO.", "KLV4829137", cap=15)
    field(c, 204, 198, "SURNAME", "VOSS", cap=16)
    field(c, 204, 240, "GIVEN NAMES", "ELENA MARA", cap=16)
    field(c, 204, 282, "NATIONALITY", "KALVERAN", cap=16)
    field(c, 204, 324, "DATE OF BIRTH", "14 MAR 1988", cap=15)
    field(c, 400, 324, "SEX", "F", cap=15)
    field(c, 204, 366, "PLACE OF BIRTH", "PORT VESNA", cap=15)
    field(c, 204, 408, "DATE OF ISSUE", "02 JUN 2023", cap=15)
    field(c, 204, 450, "DATE OF EXPIRY", "01 JUN 2033", cap=15)
    field(c, 204, 492, "AUTHORITY", "MINISTRY OF THE INTERIOR - VESNA", cap=13)
    # MRZ
    c.line(s(34), s(556), s(490), s(556), 1.0 * SS, INK)
    draw_text(c, 262, 566, "SEE PAGE 3 FOR ENDORSEMENTS", 8, GREY, weight=0.13,
              align="center")
    l1, l2 = mrz_lines()
    draw_text(c, 262, 584, l1, 11.5, INK, weight=0.12, spacing=0.2, align="center")
    draw_text(c, 262, 606, l2, 11.5, INK, weight=0.12, spacing=0.2, align="center")
    c.line(s(34), s(646), s(490), s(646), 1.0 * SS, GOLD)
    draw_text(c, 262, 656, "THIS PASSPORT IS THE PROPERTY OF THE REPUBLIC OF KALVERA",
              8, GREY, weight=0.12, align="center")
    draw_text(c, 262, 672, "32 PAGES  \u2022  IF FOUND PLEASE RETURN TO THE NEAREST KALVERAN MISSION",
              8, GREY, weight=0.12, align="center")


def draw_right_page(c):
    x0, x1, y0, y1 = 514, 1010, 14, 710
    guilloche(c, x0 + 10, y0 + 250, x1 - 10, y1 - 100, rgb("#e3dcc2"), step=11)
    frame(c, x0 + 6, y0 + 6, x1 - 6, y1 - 6, GOLD, width=1.0)
    draw_text(c, 546, 30, "NO. KLV4829137", 8.5, GREY, weight=0.12)
    draw_text(c, 762, 30, "VISAS", 19, INK, weight=0.14, spacing=2.0, align="center")
    draw_text(c, 978, 30, "3", 12, INK, weight=0.13, align="right")
    # --- Vostria visa vignette
    vx0, vy0, vx1, vy1 = 546, 62, 978, 238
    c.rect(s(vx0), s(vy0), s(vx1), s(vy1), rgb("#eef1ec"))
    frame(c, vx0, vy0, vx1, vy1, TEAL, width=2.0)
    frame(c, vx0 + 5, vy0 + 5, vx1 - 5, vy1 - 5, TEAL, width=0.8)
    for d in range(vx0, vx1, 14):
        c.line(s(d), s(vy1), s(d + 30), s(vy0), 0.6 * SS, rgb("#dde5df"))
    coat_of_arms(c, 592, 118, 40, BURG)
    draw_text(c, 640, 76, "REPUBLIC OF VOSTRIA", 14, BURG, weight=0.14, spacing=0.6)
    draw_text(c, 640, 98, "VISA", 24, INK, weight=0.15, spacing=3.0)
    draw_text(c, 640, 132, "MULTIPLE ENTRY  -  90 DAYS", 12.5, INK, weight=0.13)
    draw_text(c, 640, 154, "ISSUED 18 JUL 2025  -  VESNA", 12.5, INK, weight=0.13)
    draw_text(c, 640, 176, "VALID UNTIL 16 OCT 2025", 12.5, INK, weight=0.13)
    draw_text(c, 640, 200, "VISA NO. VST-2025-07714", 11, GREY, weight=0.13)
    # --- stamps: one coherent trip, all after the 02 JUN 2023 issue
    circular_stamp(c, 648, 318, 62, STAMP_BLUE, "PORT VESNA", "KALVERA",
                   "DEPARTURE", "12 AUG 2025")
    rect_stamp(c, 742, 272, 966, 352, -4, STAMP_PURPLE,
               [("VOSTRIA", 15), ("ENTRY", 15), ("13 AUG 2025", 12.5)],
               small="NORTH GATE")
    rect_stamp(c, 546, 412, 762, 492, 3, STAMP_RED,
               [("TARNOVIA", 15), ("ENTRY", 15), ("03 SEP 2025", 12.5)],
               small="KOROVO BRIDGE")
    circular_stamp(c, 872, 452, 60, STAMP_GREEN, "MEREK", "EXIT - HARBOUR",
                   "EXIT", "21 NOV 2025")
    circular_stamp(c, 622, 552, 50, STAMP_BLUE_LT, "PORT VESNA", "KALVERA",
                   "ARRIVAL", "28 NOV 2025")
    fee_stamp(c, 742, 540, 930, 592, -10, STAMP_RED)
    # --- endorsements: the telling detail
    ex0, ey0, ex1, ey1 = 546, 612, 978, 700
    c.rect(s(ex0), s(ey0), s(ex1), s(ey1), rgb("#fbf7ea"))
    frame(c, ex0, ey0, ex1, ey1, BURG, width=1.2)
    draw_text(c, ex0 + 12, ey0 + 8, "ENDORSEMENTS / OBSERVATIONS", 10, BURG,
              weight=0.14, spacing=0.5)
    # tiny lighthouse beside the text
    lx = ex0 + 26
    c.poly([(s(lx - 5), s(ey1 - 12)), (s(lx - 3), s(ey0 + 34)),
            (s(lx + 3), s(ey0 + 34)), (s(lx + 5), s(ey1 - 12))], TEAL)
    c.rect(s(lx - 4), s(ey0 + 30), s(lx + 4), s(ey0 + 34), TEAL)
    c.line(s(lx - 8), s(ey0 + 32), s(lx - 13), s(ey0 + 29), 1.2 * SS, GOLD)
    c.line(s(lx + 8), s(ey0 + 32), s(lx + 13), s(ey0 + 29), 1.2 * SS, GOLD)
    draw_text(c, ex0 + 46, ey0 + 26, "BEARER IS KEEPER OF THE VESNA LIGHT.", 11, INK,
              weight=0.13)
    draw_text(c, ex0 + 46, ey0 + 42, "PERMITTED TO CROSS THE NORTH GATE AFTER", 11, INK,
              weight=0.13)
    draw_text(c, ex0 + 46, ey0 + 58, "DARK WITHOUT FURTHER STAMP.", 11, INK,
              weight=0.13)
    draw_text(c, ex0 + 46, ey0 + 74, "- MINISTRY OF THE INTERIOR, VESNA", 9.5, GREY,
              weight=0.13)


# ---------------------------------------------------------------- main
def build():
    c = Canvas(SW, SH)
    c.fill(PAPER_DK)
    # spread shadow + gutter
    c.rect(s(10), s(10), s(1014), s(714), PAPER)
    c.rect(s(508), s(14), s(516), s(710), rgb("#d9d0b4"))
    draw_left_page(c)
    draw_right_page(c)
    return c.downsample()


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    data = build()
    n = write_png(path, data, W, H)
    assert n <= 1048576, f"entry.png too large: {n} bytes"
    print(f"wrote {path}: {W}x{H}, {n} bytes")


if __name__ == "__main__":
    main()
