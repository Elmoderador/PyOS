"""Formato de arranque v2 (ARCHITECTURE_V2 §7, SPEC_UC §4.2 y §9; decisiones D4, D14, D17).

Lo comparten el kernel (que lo escribe durante una actualización) y el bootloader (que lo lee
y descuenta intentos): la herramienta de construcción copia este módulo dentro de
`bootloader.zip`, así que no importa nada del kernel salvo la biblioteca estándar.

Disco de PyOS (sectores de 512 bytes):

    LBA 0              registro de arranque v2 (principal)
    LBA 1..31          almacén de claves, copia 0
    LBA 32..62         almacén de claves, copia 1
    LBA 63             registro de arranque v2 (respaldo; se escribe ANTES que el principal)
    LBA 64..4159       zona del conjunto A: cabecera (manifiesto instalado + firma) + kernel
    LBA 4160..8191     zona del conjunto B: igual
    LBA 8192..         volumen de sistema A | volumen de sistema B | volumen de datos

Los manifiestos instalados van en la cabecera de la zona de su conjunto (64 sectores, 32 KiB)
y no en LBA 1..62 como decía la propuesta: dos manifiestos de hasta 16 KiB no caben en 31 KiB.

Un volumen de sistema es `nblocks` bloques de 4 KiB de PyFS seguidos de su árbol verity; la
raíz va en el manifiesto firmado. El asset `system` son exactamente esos bytes (UC-34).
"""
import hashlib
import struct

SECTOR = 512
REC_LBAS = (0, 63)                    # principal, respaldo
KS_LBAS = (1, 32)
KS_SECTORS = 31
SET_LBAS = (64, 4160)
SET_SECTORS = (4096, 4032)
SET_HDR_SECTORS = 64
SYS_LBA = 8192
SET_NAMES = ("A", "B")

BOOT_ABI = 2                          # formato de arranque que entiende este código
STATE_EMPTY, STATE_TRIAL, STATE_GOOD, STATE_BAD = 0, 1, 2, 3
STATE_NAMES = ("vacía", "probando", "buena", "mala")
TRIAL_TRIES = 3                       # UC-42
CHANNELS = ("stable", "beta", "sandbox")
COMPONENTS = ("kernel", "system", "bootloader")

MAGIC = b"PYOSBOOT"
VERSION = 2
_HEAD = "<8sHHQBH160sIQQ"             # magic, versión, flags, seq, activo, boot_abi, cmdline,
#                                       sectores por ranura de sistema, data_lba, data_sectors
_SET = "<BBB16sIQ20s"                 # estado, intentos, canal, versión, tamaño del kernel,
#                                       sys_lba, released
_TAIL = "<III20s"                     # índices anti-retroceso kernel/system/bootloader,
#                                       released del último manifiesto confirmado (UC-24)
_SUM_AT = 446


class FormatError(ValueError):
    pass


def kernel_max(i):
    return (SET_SECTORS[i] - SET_HDR_SECTORS) * SECTOR


def kernel_lba(i):
    return SET_LBAS[i] + SET_HDR_SECTORS


class SetInfo(object):
    __slots__ = ("state", "tries", "channel", "version", "kernel_size", "sys_lba", "released")

    def __init__(self, state=STATE_EMPTY, tries=0, channel="stable", version="", kernel_size=0,
                 sys_lba=0, released=""):
        self.state, self.tries, self.channel, self.version = state, tries, channel, version
        self.kernel_size, self.sys_lba, self.released = kernel_size, sys_lba, released

    def copy(self):
        return SetInfo(self.state, self.tries, self.channel, self.version, self.kernel_size,
                       self.sys_lba, self.released)

    def as_dict(self):
        return {"state": STATE_NAMES[self.state], "tries": self.tries, "channel": self.channel,
                "version": self.version, "kernel_size": self.kernel_size,
                "released": self.released}


class BootRecordV2(object):
    def __init__(self, cmdline="", sys_sectors=0, data_lba=0, data_sectors=0):
        self.seq = 0
        self.active = 0
        self.boot_abi = BOOT_ABI
        self.flags = 0
        self.cmdline = cmdline
        self.sys_sectors = sys_sectors
        self.data_lba = data_lba
        self.data_sectors = data_sectors
        self.sets = [SetInfo(), SetInfo()]
        self.rollback = {"kernel": 0, "system": 0, "bootloader": 0}
        self.last_released = ""

    def copy(self):
        r = BootRecordV2(self.cmdline, self.sys_sectors, self.data_lba, self.data_sectors)
        r.seq, r.active, r.boot_abi, r.flags = self.seq, self.active, self.boot_abi, self.flags
        r.sets = [s.copy() for s in self.sets]
        r.rollback = dict(self.rollback)
        r.last_released = self.last_released
        return r

    def pack(self):
        cmd = self.cmdline.encode("utf-8")
        if len(cmd) > 160:
            raise FormatError("cmdline demasiado larga (máx 160 bytes)")
        out = struct.pack(_HEAD, MAGIC, VERSION, self.flags, self.seq, self.active, self.boot_abi,
                          cmd, self.sys_sectors, self.data_lba, self.data_sectors)
        for s in self.sets:
            out += struct.pack(_SET, s.state, s.tries, CHANNELS.index(s.channel),
                               s.version.encode("ascii"), s.kernel_size, s.sys_lba,
                               s.released.encode("ascii"))
        out += struct.pack(_TAIL, self.rollback["kernel"], self.rollback["system"],
                           self.rollback["bootloader"], self.last_released.encode("ascii"))
        if len(out) > _SUM_AT:
            raise FormatError("registro demasiado grande")
        out = out.ljust(_SUM_AT, b"\0")
        out += hashlib.sha256(out).digest()
        return out.ljust(510, b"\0") + b"\x55\xaa"

    @classmethod
    def unpack(cls, sector):
        if type(sector) is not bytes or len(sector) != SECTOR or sector[510:] != b"\x55\xaa":
            raise FormatError("sin firma 0x55AA")
        if sector[:8] != MAGIC:
            raise FormatError("no es un disco PyOS")
        ver = struct.unpack_from("<H", sector, 8)[0]
        if ver != VERSION:
            raise FormatError("registro de arranque v%d (este sistema necesita v%d)" % (ver, VERSION))
        if hashlib.sha256(sector[:_SUM_AT]).digest() != sector[_SUM_AT:_SUM_AT + 32]:
            raise FormatError("suma de comprobación del registro incorrecta")
        head = struct.unpack_from(_HEAD, sector, 0)
        r = cls(head[6].rstrip(b"\0").decode("utf-8"), head[7], head[8], head[9])
        r.flags, r.seq, r.active, r.boot_abi = head[2], head[3], head[4], head[5]
        if r.active not in (0, 1):
            raise FormatError("conjunto activo no válido")
        off = struct.calcsize(_HEAD)
        for i in range(2):
            st, tries, ch, ver_s, ksize, slba, rel = struct.unpack_from(_SET, sector, off)
            off += struct.calcsize(_SET)
            if st > STATE_BAD or ch >= len(CHANNELS) or tries > TRIAL_TRIES:
                raise FormatError("conjunto %s no válido" % SET_NAMES[i])
            r.sets[i] = SetInfo(st, tries, CHANNELS[ch], ver_s.rstrip(b"\0").decode("ascii"),
                                ksize, slba, rel.rstrip(b"\0").decode("ascii"))
        rk, rs, rb, last = struct.unpack_from(_TAIL, sector, off)
        r.rollback = {"kernel": rk, "system": rs, "bootloader": rb}
        r.last_released = last.rstrip(b"\0").decode("ascii")
        return r


def read_record(disk):
    """El registro válido de mayor secuencia (principal o respaldo). Devuelve (rec, errores)."""
    best, errs = None, []
    for lba in REC_LBAS:
        try:
            r = BootRecordV2.unpack(bytes(disk.read(lba, 1)))
        except FormatError as e:
            errs.append("LBA %d: %s" % (lba, e))
            continue
        if best is None or r.seq > best.seq:
            best = r
    return best, errs


def write_record(disk, rec):
    """Escritura segura: secuencia +1; primero el respaldo (LBA 63), después el principal."""
    rec.seq += 1
    data = rec.pack()
    disk.write(REC_LBAS[1], data)
    disk.flush()
    disk.write(REC_LBAS[0], data)
    disk.flush()
    return rec


# ---------------------------------------------------------------- cabecera de un conjunto
SETHDR_MAGIC = b"PYOSSET1"


def pack_set_header(manifest, sig):
    body = SETHDR_MAGIC + struct.pack("<HH", len(manifest), len(sig)) + manifest + sig
    body += hashlib.sha256(body).digest()
    if len(body) > SET_HDR_SECTORS * SECTOR:
        raise FormatError("manifiesto instalado demasiado grande")
    return body.ljust(((len(body) + SECTOR - 1) // SECTOR) * SECTOR, b"\0")


def read_set_header(disk, i):
    """(manifiesto, firma) instalados del conjunto i, o FormatError."""
    raw = bytes(disk.read(SET_LBAS[i], SET_HDR_SECTORS))
    if raw[:8] != SETHDR_MAGIC:
        raise FormatError("conjunto %s sin manifiesto instalado" % SET_NAMES[i])
    ml, sl = struct.unpack_from("<HH", raw, 8)
    end = 12 + ml + sl
    if end + 32 > len(raw):
        raise FormatError("cabecera del conjunto %s corrupta" % SET_NAMES[i])
    if hashlib.sha256(raw[:end]).digest() != raw[end:end + 32]:
        raise FormatError("cabecera del conjunto %s corrupta" % SET_NAMES[i])
    return raw[12:12 + ml], raw[12 + ml:end]


# ---------------------------------------------------------------- volumen de sistema
VBLOCK = 4096
FANOUT = VBLOCK // 32


def tree_blocks(nblocks):
    total, n = 0, nblocks
    while True:
        n = (n + FANOUT - 1) // FANOUT
        total += n
        if n == 1:
            return total


def split_system(size):
    """Tamaño del asset system -> (bloques de datos, bloques del árbol). FormatError si no es
    un tamaño posible."""
    if size <= 0 or size % VBLOCK:
        raise FormatError("el volumen de sistema debe ser un múltiplo de 4 KiB")
    total = size // VBLOCK
    lo, hi = 1, total
    while lo <= hi:
        mid = (lo + hi) // 2
        t = mid + tree_blocks(mid)
        if t == total:
            return mid, total - mid
        if t < total:
            lo = mid + 1
        else:
            hi = mid - 1
    raise FormatError("tamaño de volumen de sistema imposible")


def sys_lba(rec, i):
    return SYS_LBA + i * rec.sys_sectors


# ---------------------------------------------------------------- almacén de claves
KS_MAGIC = b"PYOSKS1\n"


def pack_keystore(chain):
    """chain: lista de (registro UCKEYREC, firma UCSIG) en orden de seq."""
    body = KS_MAGIC + struct.pack("<H", len(chain))
    for rec, sig in chain:
        body += struct.pack("<HH", len(rec), len(sig)) + rec + sig
    body += hashlib.sha256(body).digest()
    if len(body) > KS_SECTORS * SECTOR:
        raise FormatError("almacén de claves lleno (%d bytes)" % len(body))
    return body.ljust(KS_SECTORS * SECTOR, b"\0")


def unpack_keystore(raw):
    if raw[:8] != KS_MAGIC:
        raise FormatError("sin almacén de claves")
    n = struct.unpack_from("<H", raw, 8)[0]
    off, chain = 10, []
    for _ in range(n):
        if off + 4 > len(raw):
            raise FormatError("almacén de claves truncado")
        rl, sl = struct.unpack_from("<HH", raw, off)
        off += 4
        if off + rl + sl > len(raw):
            raise FormatError("almacén de claves truncado")
        chain.append((raw[off:off + rl], raw[off + rl:off + rl + sl]))
        off += rl + sl
    if hashlib.sha256(raw[:off]).digest() != raw[off:off + 32]:
        raise FormatError("suma del almacén de claves incorrecta")
    return chain


def read_keystore(disk):
    """La copia válida con la cadena más larga. Devuelve (cadena, índice de copia | None)."""
    best, which = None, None
    for i, lba in enumerate(KS_LBAS):
        try:
            chain = unpack_keystore(bytes(disk.read(lba, KS_SECTORS)))
        except FormatError:
            continue
        if best is None or len(chain) > len(best):
            best, which = chain, i
    return (best or []), which


def write_keystore(disk, chain):
    """Copia 1 primero, después la 0: en un corte, una de las dos sigue siendo válida."""
    data = pack_keystore(chain)
    disk.write(KS_LBAS[1], data)
    disk.flush()
    disk.write(KS_LBAS[0], data)
    disk.flush()
