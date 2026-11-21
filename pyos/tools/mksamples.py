"""Genera las imágenes de ejemplo de LOOK (/usr/share/images) de forma reproducible:
python -m pyos.tools.mksamples"""
import math
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "packages" / "look" / "usr" / "share" / "images"


def bmp24(w, h, px):
    stride = (w * 3 + 3) & ~3
    rows = []
    for j in range(h - 1, -1, -1):
        r = bytearray()
        for i in range(w):
            c = px[j][i]
            r += bytes((c & 0xFF, (c >> 8) & 0xFF, c >> 16))
        rows.append(bytes(r) + b"\0" * (stride - 3 * w))
    data = b"".join(rows)
    head = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
    head += struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    return head + data


def bmp8(w, h, idx, pal):
    stride = (w + 3) & ~3
    data = b"".join(bytes(idx[j]) + b"\0" * (stride - w) for j in range(h - 1, -1, -1))
    p = b"".join(bytes((c & 0xFF, (c >> 8) & 0xFF, c >> 16, 0)) for c in pal)
    off = 54 + len(p)
    head = b"BM" + struct.pack("<IHHI", off + len(data), 0, 0, off)
    head += struct.pack("<IiiHHIIiiII", 40, w, h, 1, 8, 0, len(data), 2835, 2835, len(pal), 0)
    return head + p + data


FONT = {  # 5x7
    "P": ["1111.", "1...1", "1...1", "1111.", "1....", "1....", "1...."],
    "y": [".....", ".....", "1...1", "1...1", ".1111", "....1", ".111."],
    "O": [".111.", "1...1", "1...1", "1...1", "1...1", "1...1", ".111."],
    "S": [".1111", "1....", "1....", ".111.", "....1", "....1", "1111."],
}


def landscape(w=320, h=200):
    px = [[0] * w for _ in range(h)]
    bands = [0x0B1E3F, 0x13305C, 0x1D4479, 0x2A5A96, 0x3B71B0, 0x5287C4, 0x6E9ED3]
    for y in range(h):
        b = min(len(bands) - 1, y * len(bands) // (h * 6 // 10))
        for x in range(w):
            px[y][x] = bands[b]
    for y in range(h):                      # sol
        for x in range(w):
            if (x - 240) ** 2 + (y - 52) ** 2 < 24 ** 2:
                px[y][x] = 0xFDE68A
    for layer, (col, amp, base, f) in enumerate([(0x334155, 26, 120, 0.03), (0x1E293B, 18, 140, 0.05),
                                                 (0x14532D, 10, 165, 0.08)]):
        for x in range(w):
            top = int(base - amp * (0.5 + 0.5 * math.sin(x * f + layer * 2)))
            for y in range(max(0, top), h):
                px[y][x] = col
    s = 6                                    # texto "PyOS" en píxeles grandes
    x0 = 24
    for ch in "PyOS":
        for j, row in enumerate(FONT[ch]):
            for i, c in enumerate(row):
                if c == "1":
                    for yy in range(s):
                        for xx in range(s):
                            px[24 + j * s + yy][x0 + i * s + xx] = 0xFFFFFF
        x0 += 6 * s
    return bmp24(w, h, px)


SNAKE = [
    "................",
    "....gggggg......",
    "...gGGGGGGg.....",
    "...gGwkGGGg.....",
    "...gGGGGGGg.....",
    "....gggGGg..r...",
    ".......gGg.rr...",
    "......gGGg......",
    ".....gGGg.......",
    "....gGGg........",
    "...gGGg.....yy..",
    "...gGGggggggGy..",
    "....gGGGGGGGGg..",
    ".....ggggggggg..",
    "................",
    "................",
]


def snake():
    pal = [0x0F172A, 0x15803D, 0x4ADE80, 0xFFFFFF, 0x000000, 0xEF4444, 0xFACC15]
    m = {".": 0, "g": 1, "G": 2, "w": 3, "k": 4, "r": 5, "y": 6}
    s = 8
    idx = [[m[SNAKE[j // s][i // s]] for i in range(16 * s)] for j in range(16 * s)]
    return bmp8(16 * s, 16 * s, idx, pal)


def colors_ppm(w=256, h=96):
    out = bytearray()
    for y in range(h):
        for x in range(w):
            hue = x / w * 6
            i = int(hue) % 6
            f = hue - int(hue)
            v = 1 - y / h * 0.8
            q, t = v * (1 - f), v * f
            r, g, b = [(v, t, 0), (q, v, 0), (0, v, t), (0, q, v), (t, 0, v), (v, 0, q)][i]
            out += bytes((int(r * 255), int(g * 255), int(b * 255)))
    return b"P6\n# PyOS: tabla de colores\n%d %d\n255\n" % (w, h) + bytes(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "paisaje.bmp").write_bytes(landscape())
    (OUT / "serpiente.bmp").write_bytes(snake())
    (OUT / "colores.ppm").write_bytes(colors_ppm())
    for f in sorted(OUT.iterdir()):
        print(f, f.stat().st_size)


if __name__ == "__main__":
    main()
