"""Utilidades de paquetes: direcciones, sumas de comprobación y cabeceras."""
import array
import struct
import sys

BROADCAST_MAC = b"\xff" * 6
ETH_IP, ETH_ARP = 0x0800, 0x0806
PROTO_ICMP, PROTO_TCP, PROTO_UDP = 1, 6, 17
_LITTLE = sys.byteorder == "little"


def ip2s(ip):
    return "%d.%d.%d.%d" % tuple(ip)


def s2ip(s):
    parts = s.strip().split(".")
    if len(parts) != 4:
        raise ValueError("dirección IPv4 inválida: %r" % s)
    b = bytes(int(p) for p in parts)
    return b


def is_ip(s):
    try:
        s2ip(s)
        return True
    except (ValueError, OverflowError):
        return False


def mac2s(m):
    return ":".join("%02x" % b for b in m)


def checksum(data, initial=0):
    """Suma de comprobación de Internet (complemento a uno de palabras de 16 bits)."""
    if len(data) & 1:
        data = bytes(data) + b"\x00"
    a = array.array("H", bytes(data))
    s = sum(a) + initial
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    s = ~s & 0xFFFF
    if _LITTLE:                       # las palabras se sumaron en orden del host
        s = ((s & 0xFF) << 8) | (s >> 8)
    return s


def pseudo_sum(src, dst, proto, length):
    """Suma parcial (orden del host, sin complementar) de la pseudo-cabecera TCP/UDP."""
    a = array.array("H", src + dst + struct.pack("!BBH", 0, proto, length))
    return sum(a)


def eth(dst, src, etype, payload):
    return dst + src + struct.pack("!H", etype) + payload


def ipv4(src, dst, proto, payload, ident, ttl=64):
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), ident & 0xFFFF, 0x4000,
                      ttl, proto, 0, src, dst)
    c = checksum(hdr)
    return hdr[:10] + struct.pack("!H", c) + hdr[12:] + payload


def udp(src, dst, sport, dport, payload):
    ln = 8 + len(payload)
    hdr = struct.pack("!HHHH", sport, dport, ln, 0)
    c = checksum(hdr + payload, pseudo_sum(src, dst, PROTO_UDP, ln)) or 0xFFFF
    return struct.pack("!HHHH", sport, dport, ln, c) + payload


def tcp(src, dst, sport, dport, seq, ack, flags, window, payload=b"", mss=None):
    opts = b""
    if mss is not None:
        opts = struct.pack("!BBH", 2, 4, mss)
    off = (20 + len(opts)) // 4
    hdr = struct.pack("!HHIIBBHHH", sport, dport, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF,
                      off << 4, flags, min(window, 0xFFFF), 0, 0) + opts
    seg = hdr + payload
    c = checksum(seg, pseudo_sum(src, dst, PROTO_TCP, len(seg)))
    return seg[:16] + struct.pack("!H", c) + seg[18:]
