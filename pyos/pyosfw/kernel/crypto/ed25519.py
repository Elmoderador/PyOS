"""Verificación de firmas Ed25519 (RFC 8032), en Python puro. Solo verifica: el kernel no
firma ni guarda claves privadas.

Reglas (estrictas, como libsodium):
- firma de 64 bytes y clave pública de 32; S < L (sin maleabilidad);
- codificaciones de punto canónicas (y < p) y que estén en la curva;
- se rechazan la clave pública y R de orden pequeño (ataques de claves débiles);
- ecuación sin cofactor: [S]B == R + [k]A, con k = SHA-512(R || A || M) mod L.

Coste: una multiplicación escalar doble (Straus, 253 duplicaciones) en coordenadas
extendidas. Del orden de milisegundos en CPython nativo [medido en tests/test_crypto.py].
"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
_BY = 4 * pow(5, P - 2, P) % P
_BX = None  # se calcula abajo


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_BX = _recover_x(_BY, 0)
B = (_BX, _BY, 1, _BX * _BY % P)                # coordenadas extendidas (X, Y, Z, T)
IDENT = (0, 1, 1, 0)


def _add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(p):
    x1, y1, z1, _ = p
    a = x1 * x1 % P
    b = y1 * y1 % P
    c = 2 * z1 * z1 % P
    h = a + b
    e = h - (x1 + y1) * (x1 + y1)
    g = a - b
    f = c + g
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _eq(p, q):
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _neg(p):
    x, y, z, t = p
    return (P - x, y, z, P - t)


def _decode(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _small_order(pt):
    q = pt
    for _ in range(3):
        q = _double(q)
    return _eq(q, IDENT)


def _double_mul(s, b, k, a):
    """[s]b + [k]a con una sola cadena de duplicaciones (Straus)."""
    ba = _add(b, a)
    acc = IDENT
    for i in range(max(s.bit_length(), k.bit_length()) - 1, -1, -1):
        acc = _double(acc)
        bs, bk = (s >> i) & 1, (k >> i) & 1
        if bs and bk:
            acc = _add(acc, ba)
        elif bs:
            acc = _add(acc, b)
        elif bk:
            acc = _add(acc, a)
    return acc


def verify(public_key, message, signature):
    """True si `signature` es una firma Ed25519 válida de `message` con `public_key`."""
    if type(public_key) is not bytes or type(signature) is not bytes \
            or type(message) not in (bytes, bytearray):
        return False
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode(public_key)
    r = _decode(signature[:32])
    if a is None or r is None or _small_order(a) or _small_order(r):
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + bytes(message)).digest(),
                       "little") % L
    # [S]B - [k]A == R
    return _eq(_double_mul(s, B, k, _neg(a)), r)
