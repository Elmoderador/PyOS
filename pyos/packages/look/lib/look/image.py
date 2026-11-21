# /lib/look/image.py — imágenes para LOOK: BMP (1/4/8/24/32 bits, sin comprimir) y
# PPM/PGM (P6/P5), lectura; BMP de 24 bits, escritura.
# Una imagen es (ancho, alto, bytearray RGB). Las conversiones usan rebanadas con paso
# (las hace el intérprete anfitrión de una vez) en lugar de bucles por píxel en la PVM.


def _u16(b, o):
    return b[o] | b[o + 1] << 8


def _u32(b, o):
    return b[o] | b[o + 1] << 8 | b[o + 2] << 16 | b[o + 3] << 24


def _s32(b, o):
    v = _u32(b, o)
    return v - (1 << 32) if v & 0x80000000 else v


def _p16(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def _p32(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])


def _bgr_to_rgb(src, step, n):
    """n píxeles de `src` con `step` bytes cada uno en orden B,G,R(,X) -> RGB."""
    out = bytearray(3 * n)
    out[0::3] = src[2:2 + step * n:step]
    out[1::3] = src[1:1 + step * n:step]
    out[2::3] = src[0:step * n:step]
    return out


def load_bmp(data):
    if data[:2] != b"BM" or len(data) < 54:
        raise ValueError("no es un BMP")
    off = _u32(data, 10)
    hsize = _u32(data, 14)
    w = _s32(data, 18)
    h = _s32(data, 22)
    bpp = _u16(data, 28)
    comp = _u32(data, 30) if hsize >= 40 else 0
    if comp not in (0, 3) or (comp == 3 and bpp != 32):
        raise ValueError("BMP comprimido (no soportado)")
    top_down = h < 0
    h = abs(h)
    if w <= 0 or h <= 0 or w * h > 4 * 1024 * 1024:
        raise ValueError("tamaño de BMP no válido")
    stride = ((w * bpp + 31) // 32) * 4
    if off + stride * h > len(data):
        raise ValueError("BMP truncado")
    pal = None
    if bpp <= 8:
        ncol = _u32(data, 46) if hsize >= 40 else 0
        ncol = ncol or (1 << bpp)
        p = data[14 + hsize:14 + hsize + 4 * ncol]
        pal = [bytes([p[i + 2], p[i + 1], p[i]]) for i in range(0, len(p), 4)]
    out = bytearray()
    for j in range(h):
        r = j if top_down else h - 1 - j
        row = data[off + r * stride:off + (r + 1) * stride]
        if bpp == 24:
            out += _bgr_to_rgb(row, 3, w)
        elif bpp == 32:
            out += _bgr_to_rgb(row, 4, w)
        elif bpp == 8:
            out += b"".join([pal[i] if i < len(pal) else b"\0\0\0" for i in row[:w]])
        elif bpp in (1, 4):
            per = 8 // bpp
            mask = (1 << bpp) - 1
            idx = []
            for byte in row[:(w + per - 1) // per]:
                for k in range(per):
                    idx.append((byte >> (8 - bpp * (k + 1))) & mask)
            out += b"".join([pal[i] if i < len(pal) else b"\0\0\0" for i in idx[:w]])
        else:
            raise ValueError("BMP de %d bits no soportado" % bpp)
    return w, h, out


def _pnm_tokens(data, n):
    toks = []
    i = 2
    while len(toks) < n:
        while i < len(data) and data[i] in b" \t\r\n":
            i += 1
        if i < len(data) and data[i] == 35:          # '#': comentario
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            continue
        s = i
        while i < len(data) and data[i] not in b" \t\r\n#":
            i += 1
        if s == i:
            raise ValueError("PNM truncado")
        toks.append(int(data[s:i]))
    return toks, i + 1


def load_pnm(data):
    kind = data[:2]
    if kind not in (b"P6", b"P5"):
        raise ValueError("solo PPM/PGM binarios (P6/P5)")
    (w, h, mx), off = _pnm_tokens(data, 3)
    if mx != 255:
        raise ValueError("solo 8 bits por canal")
    if w * h > 4 * 1024 * 1024:
        raise ValueError("imagen demasiado grande")
    if kind == b"P6":
        px = bytearray(data[off:off + 3 * w * h])
    else:
        g = data[off:off + w * h]
        px = bytearray(3 * len(g))
        px[0::3] = g
        px[1::3] = g
        px[2::3] = g
    if len(px) != 3 * w * h:
        raise ValueError("PNM truncado")
    return w, h, px


def load(path):
    data = read_file(path)
    if data[:2] == b"BM":
        return load_bmp(data)
    if data[:2] in (b"P6", b"P5"):
        return load_pnm(data)
    raise ValueError("formato no reconocido (BMP, PPM o PGM)")


def save_bmp(path, w, h, px):
    stride = (w * 3 + 3) & ~3
    pad = b"\0" * (stride - w * 3)
    size = 54 + stride * h
    head = (b"BM" + _p32(size) + _p32(0) + _p32(54) + _p32(40) + _p32(w) + _p32(h) +
            _p16(1) + _p16(24) + _p32(0) + _p32(stride * h) + _p32(2835) + _p32(2835) +
            _p32(0) + _p32(0))
    rows = [head]
    for j in range(h - 1, -1, -1):
        row = px[j * w * 3:(j + 1) * w * 3]
        bgr = bytearray(3 * w)
        bgr[0::3] = row[2::3]
        bgr[1::3] = row[1::3]
        bgr[2::3] = row[0::3]
        rows.append(bytes(bgr) + pad)
    write_file(path, b"".join(rows))


def shrink(w, h, px, k):
    """Reducción entera por k (vecino más cercano), con rebanadas."""
    if k <= 1:
        return w, h, px
    nw, nh = w // k, h // k
    out = bytearray()
    for j in range(nh):
        row = px[(j * k) * w * 3:(j * k + 1) * w * 3]
        r = bytearray(3 * nw)
        r[0::3] = row[0:3 * k * nw:3 * k]
        r[1::3] = row[1:3 * k * nw:3 * k]
        r[2::3] = row[2:3 * k * nw:3 * k]
        out += r
    return nw, nh, out
