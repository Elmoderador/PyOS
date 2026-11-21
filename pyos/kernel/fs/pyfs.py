"""PyFS: sistema de archivos en disco de PyOS (estilo ext2 simplificado).

Disposición (bloques de 4 KiB, relativos al inicio de la partición):
    0                 superbloque
    1                 bitmap de inodos (hasta 32768 inodos)
    2 .. 2+B-1        bitmap de bloques
    ..                tabla de inodos (128 B por inodo)
    data_start ..     datos

Inodo: 12 punteros directos + 1 indirecto simple  => tamaño máx. ~4,05 MiB.
Directorios: entradas de 64 bytes (ino u32, len u8, tipo u8, nombre 58 B).
Sin journaling: el flag `clean` del superbloque detecta montajes sucios y
dispara `fsck`, que reconstruye bitmaps y contadores de enlaces.
"""

import struct

from ..errors import (KError, EBUSY, EEXIST, EFBIG, EINVAL, EIO, EISDIR, ENOENT, ENOSPC,
                      ENOTDIR, ENOTEMPTY)
from .vfs import FileOps, O_ACCMODE, O_APPEND, O_CREAT, O_EXCL, O_RDONLY, O_TRUNC, check_name

BLOCK = 4096
MAGIC = b"PYFS"
VERSION = 1
INODE_SIZE = 128
IPB = BLOCK // INODE_SIZE
NDIRECT = 12
NINDIRECT = BLOCK // 4
MAX_FILE = (NDIRECT + NINDIRECT) * BLOCK
ROOT_INO = 1
DIRENT = 64
T_FREE, T_FILE, T_DIR = 0, 1, 2
TYPE_NAMES = {T_FILE: "file", T_DIR: "dir"}

_SB = struct.Struct("<4sIIIIIIIIIIIIId")
_SB_FIELDS = ("magic", "version", "block_size", "total_blocks", "inode_count", "ibmap_start",
              "bbmap_start", "bbmap_blocks", "itable_start", "itable_blocks", "data_start",
              "free_blocks", "free_inodes", "clean", "last_mount")
_INODE = struct.Struct("<HHIdd12III")
_DIRENT = struct.Struct("<IBB58s")


class Inode(object):
    __slots__ = ("mode", "links", "size", "ctime", "mtime", "direct", "indirect", "flags")

    def __init__(self, mode=T_FREE, links=0, size=0, ctime=0.0, mtime=0.0, direct=None,
                 indirect=0, flags=0):
        self.mode, self.links, self.size = mode, links, size
        self.ctime, self.mtime = ctime, mtime
        self.direct = direct if direct is not None else [0] * NDIRECT
        self.indirect, self.flags = indirect, flags

    def pack(self) -> bytes:
        return _INODE.pack(self.mode, self.links, self.size, self.ctime, self.mtime,
                           *self.direct, self.indirect, self.flags)

    @classmethod
    def unpack(cls, raw) -> "Inode":
        v = _INODE.unpack_from(raw)
        return cls(v[0], v[1], v[2], v[3], v[4], list(v[5:17]), v[17], v[18])


class PyFile(FileOps):
    def __init__(self, fs: "PyFS", ino: int):
        self.fs = fs
        self.ino = ino
        fs.open_counts[ino] = fs.open_counts.get(ino, 0) + 1

    def read(self, of, n):
        data = self.fs.read(self.ino, of.offset, n)
        of.offset += len(data)
        return data

    def write(self, of, data):
        if of.flags & O_APPEND:
            of.offset = self.fs.iget(self.ino).size
        n = self.fs.write(self.ino, of.offset, data)
        of.offset += n
        return n

    def size(self):
        return self.fs.iget(self.ino).size

    def close(self, of):
        self.fs.release(self.ino)


class PyFS:
    name = "pyfs"

    # ------------------------------------------------------------ formato
    @staticmethod
    def format(cache, clock, inode_count: int = 1024) -> None:
        total = cache.nblocks
        inode_count = min(inode_count, BLOCK * 8)
        bbmap_blocks = (total + BLOCK * 8 - 1) // (BLOCK * 8)
        itable_blocks = (inode_count + IPB - 1) // IPB
        ibmap_start, bbmap_start = 1, 2
        itable_start = bbmap_start + bbmap_blocks
        data_start = itable_start + itable_blocks
        if data_start + 8 > total:
            raise KError(ENOSPC, "partición demasiado pequeña")
        zero = bytearray(BLOCK)
        for b in range(data_start):
            cache.put(b, bytearray(zero))
        sb = dict(magic=MAGIC, version=VERSION, block_size=BLOCK, total_blocks=total,
                  inode_count=inode_count, ibmap_start=ibmap_start, bbmap_start=bbmap_start,
                  bbmap_blocks=bbmap_blocks, itable_start=itable_start, itable_blocks=itable_blocks,
                  data_start=data_start, free_blocks=total - data_start,
                  free_inodes=inode_count - 2, clean=1, last_mount=0.0)
        cache.put(0, bytearray(_SB.pack(*[sb[f] for f in _SB_FIELDS]).ljust(BLOCK, b"\0")))
        fs = PyFS.__new__(PyFS)
        fs._init_common(cache, clock, sb)
        for b in range(data_start):           # metadatos: marcados como usados
            fs._bit_set(bbmap_start, b, 1)
        fs._bit_set(ibmap_start, 0, 1)        # inodo 0 = "ninguno"
        fs._bit_set(ibmap_start, ROOT_INO, 1)
        now = clock()
        fs.iput(ROOT_INO, Inode(T_DIR, 2, 0, now, now))
        fs._dir_add(ROOT_INO, ".", ROOT_INO, T_DIR)
        fs._dir_add(ROOT_INO, "..", ROOT_INO, T_DIR)
        fs._sb_flush()
        cache.sync()

    # ------------------------------------------------------------ montaje
    def __init__(self, cache, clock):
        raw = cache.read(0)
        vals = _SB.unpack_from(raw)
        sb = dict(zip(_SB_FIELDS, vals))
        if sb["magic"] != MAGIC or sb["version"] != VERSION or sb["block_size"] != BLOCK:
            raise KError(EIO, "superbloque PyFS inválido")
        if sb["total_blocks"] > cache.nblocks:
            raise KError(EIO, "el superbloque declara más bloques de los que tiene el disco")
        cache.nblocks = sb["total_blocks"]  # la partición puede ocupar solo parte del disco
        self._init_common(cache, clock, sb)
        self.was_clean = bool(sb["clean"])
        self.sb["clean"] = 0
        self.sb["last_mount"] = clock()
        self._sb_flush()
        cache.sync()

    def _init_common(self, cache, clock, sb) -> None:
        self.cache = cache
        self.clock = clock
        self.sb = sb
        self.open_counts: dict = {}
        self.orphans: set = set()
        self.was_clean = True

    def _sb_flush(self) -> None:
        self.cache.put(0, bytearray(_SB.pack(*[self.sb[f] for f in _SB_FIELDS]).ljust(BLOCK, b"\0")))

    def sync(self) -> None:
        self._sb_flush()
        self.cache.sync()

    def unmount(self) -> None:
        for ino in list(self.orphans):
            self._free_inode(ino)
        self.orphans.clear()
        self.sb["clean"] = 1
        self.sync()

    # ------------------------------------------------------------ bitmaps
    def _bit_get(self, start: int, n: int) -> int:
        buf = self.cache.read(start + n // (BLOCK * 8))
        i = n % (BLOCK * 8)
        return (buf[i >> 3] >> (i & 7)) & 1

    def _bit_set(self, start: int, n: int, v: int) -> None:
        blk = start + n // (BLOCK * 8)
        buf = self.cache.read(blk)
        i = n % (BLOCK * 8)
        if v:
            buf[i >> 3] |= 1 << (i & 7)
        else:
            buf[i >> 3] &= ~(1 << (i & 7)) & 0xFF
        self.cache.put(blk, buf)

    def _bit_alloc(self, start: int, nbitmap: int, limit: int) -> int:
        for b in range(nbitmap):
            buf = self.cache.read(start + b)
            idx = len(buf) - len(buf.lstrip(b"\xff"))
            if idx >= len(buf):
                continue
            byte = buf[idx]
            bit = (~byte & (byte + 1)).bit_length() - 1
            n = b * BLOCK * 8 + idx * 8 + bit
            if n >= limit:
                break
            buf[idx] |= 1 << bit
            self.cache.put(start + b, buf)
            return n
        raise KError(ENOSPC)

    def _balloc(self) -> int:
        b = self._bit_alloc(self.sb["bbmap_start"], self.sb["bbmap_blocks"], self.sb["total_blocks"])
        self.sb["free_blocks"] -= 1
        self.cache.put(b, bytearray(BLOCK))  # nunca filtrar datos antiguos
        return b

    def _bfree(self, b: int) -> None:
        if b < self.sb["data_start"] or not self._bit_get(self.sb["bbmap_start"], b):
            raise KError(EIO, f"liberación de bloque inválido {b}")
        self._bit_set(self.sb["bbmap_start"], b, 0)
        self.sb["free_blocks"] += 1

    # ------------------------------------------------------------ inodos
    def _iloc(self, ino: int):
        if not 0 < ino < self.sb["inode_count"]:
            raise KError(EIO, f"inodo fuera de rango {ino}")
        return self.sb["itable_start"] + ino // IPB, (ino % IPB) * INODE_SIZE

    def iget(self, ino: int) -> Inode:
        blk, off = self._iloc(ino)
        return Inode.unpack(self.cache.read(blk)[off:off + INODE_SIZE])

    def iput(self, ino: int, inode: Inode) -> None:
        blk, off = self._iloc(ino)
        buf = self.cache.read(blk)
        buf[off:off + INODE_SIZE] = inode.pack().ljust(INODE_SIZE, b"\0")
        self.cache.put(blk, buf)

    def _ialloc(self, mode: int) -> int:
        ino = self._bit_alloc(self.sb["ibmap_start"], 1, self.sb["inode_count"])
        self.sb["free_inodes"] -= 1
        now = self.clock()
        self.iput(ino, Inode(mode, 1, 0, now, now))
        return ino

    def _free_inode(self, ino: int) -> None:
        self.truncate(ino, 0)
        self.iput(ino, Inode())
        self._bit_set(self.sb["ibmap_start"], ino, 0)
        self.sb["free_inodes"] += 1

    def release(self, ino: int) -> None:
        """Cierre de un fichero: libera inodos huérfanos (unlink con fichero abierto)."""
        c = self.open_counts.get(ino, 0) - 1
        if c <= 0:
            self.open_counts.pop(ino, None)
            if ino in self.orphans:
                self.orphans.discard(ino)
                self._free_inode(ino)
        else:
            self.open_counts[ino] = c

    # ------------------------------------------------------------ bloques de fichero
    def _bmap(self, inode: Inode, idx: int, alloc: bool) -> int:
        if idx < NDIRECT:
            b = inode.direct[idx]
            if not b and alloc:
                b = inode.direct[idx] = self._balloc()
            return b
        idx -= NDIRECT
        if idx >= NINDIRECT:
            raise KError(EFBIG)
        if not inode.indirect:
            if not alloc:
                return 0
            inode.indirect = self._balloc()
        ib = self.cache.read(inode.indirect)
        b = int.from_bytes(ib[idx * 4:idx * 4 + 4], "little")
        if not b and alloc:
            b = self._balloc()
            ib = self.cache.read(inode.indirect)
            ib[idx * 4:idx * 4 + 4] = b.to_bytes(4, "little")
            self.cache.put(inode.indirect, ib)
        return b

    def _blocks(self, inode: Inode) -> list:
        out = [b for b in inode.direct if b]
        if inode.indirect:
            ib = self.cache.read(inode.indirect)
            out += [b for b in struct.unpack_from(f"<{NINDIRECT}I", ib) if b]
            out.append(inode.indirect)
        return out

    def read(self, ino: int, off: int, n: int) -> bytes:
        inode = self.iget(ino)
        if off >= inode.size or n <= 0:
            return b""
        n = min(n, inode.size - off)
        out = bytearray()
        while n > 0:
            idx, o = divmod(off, BLOCK)
            c = min(n, BLOCK - o)
            b = self._bmap(inode, idx, False)
            out += self.cache.read(b)[o:o + c] if b else bytes(c)
            off += c
            n -= c
        return bytes(out)

    def write(self, ino: int, off: int, data: bytes) -> int:
        inode = self.iget(ino)
        if inode.mode != T_FILE:
            raise KError(EISDIR) if inode.mode == T_DIR else KError(EIO)
        return self._write_inode(ino, inode, off, data)

    def _write_inode(self, ino, inode, off, data) -> int:
        if off + len(data) > MAX_FILE:
            raise KError(EFBIG)
        pos = 0
        try:
            while pos < len(data):
                idx, o = divmod(off + pos, BLOCK)
                c = min(len(data) - pos, BLOCK - o)
                b = self._bmap(inode, idx, True)
                buf = self.cache.read(b)
                buf[o:o + c] = data[pos:pos + c]
                self.cache.put(b, buf)
                pos += c
        finally:  # escritura parcial (ENOSPC): el inodo refleja lo escrito
            inode.size = max(inode.size, off + pos)
            inode.mtime = self.clock()
            self.iput(ino, inode)
        return pos

    def truncate(self, ino: int, size: int) -> None:
        inode = self.iget(ino)
        if size >= inode.size:
            inode.size = size
            self.iput(ino, inode)
            return
        keep = (size + BLOCK - 1) // BLOCK
        for i in range(keep, NDIRECT):
            if inode.direct[i]:
                self._bfree(inode.direct[i])
                inode.direct[i] = 0
        if inode.indirect:
            ib = self.cache.read(inode.indirect)
            first = max(0, keep - NDIRECT)
            for j in range(first, NINDIRECT):
                b = int.from_bytes(ib[j * 4:j * 4 + 4], "little")
                if b:
                    self._bfree(b)
                    ib[j * 4:j * 4 + 4] = b"\0\0\0\0"
            self.cache.put(inode.indirect, ib)
            if first == 0:
                self._bfree(inode.indirect)
                inode.indirect = 0
        if size % BLOCK:  # pone a cero la cola del último bloque parcial
            b = self._bmap(inode, size // BLOCK, False)
            if b:
                buf = self.cache.read(b)
                buf[size % BLOCK:] = bytes(BLOCK - size % BLOCK)
                self.cache.put(b, buf)
        inode.size = size
        inode.mtime = self.clock()
        self.iput(ino, inode)

    # ------------------------------------------------------------ directorios
    def _dir_iter(self, dino: int):
        inode = self.iget(dino)
        raw = self.read(dino, 0, inode.size)
        for off in range(0, len(raw), DIRENT):
            ino, ln, typ, name = _DIRENT.unpack_from(raw, off)
            if ino:
                yield off, ino, name[:ln].decode("utf-8", "replace"), typ

    def _dir_lookup(self, dino: int, name: str) -> int:
        for _, ino, n, _t in self._dir_iter(dino):
            if n == name:
                return ino
        return 0

    def _dir_add(self, dino: int, name: str, ino: int, typ: int) -> None:
        enc = name.encode("utf-8")
        entry = _DIRENT.pack(ino, len(enc), typ, enc)
        inode = self.iget(dino)
        raw = self.read(dino, 0, inode.size)
        off = inode.size
        for o in range(0, len(raw), DIRENT):
            if int.from_bytes(raw[o:o + 4], "little") == 0:
                off = o
                break
        self._write_inode(dino, inode, off, entry)

    def _dir_remove(self, dino: int, name: str) -> None:
        for off, _ino, n, _t in self._dir_iter(dino):
            if n == name:
                self._write_inode(dino, self.iget(dino), off, bytes(DIRENT))
                return
        raise KError(ENOENT)

    def _dir_set_parent(self, dino: int, parent: int) -> None:
        for off, _ino, n, _t in self._dir_iter(dino):
            if n == "..":
                self._write_inode(dino, self.iget(dino), off, _DIRENT.pack(parent, 2, T_DIR, b".."))
                return

    # ------------------------------------------------------------ rutas
    def _walk(self, parts) -> int:
        ino = ROOT_INO
        for p in parts:
            if self.iget(ino).mode != T_DIR:
                raise KError(ENOTDIR)
            ino = self._dir_lookup(ino, p)
            if not ino:
                raise KError(ENOENT)
        return ino

    def _parent(self, parts):
        if not parts:
            raise KError(EBUSY, "operación sobre la raíz")
        dino = self._walk(parts[:-1])
        if self.iget(dino).mode != T_DIR:
            raise KError(ENOTDIR)
        return dino, parts[-1]

    def _create(self, parts, typ: int) -> int:
        dino, name = self._parent(parts)
        check_name(name)
        if self._dir_lookup(dino, name):
            raise KError(EEXIST)
        ino = self._ialloc(typ)
        if typ == T_DIR:
            inode = self.iget(ino)
            inode.links = 2
            self.iput(ino, inode)
            self._dir_add(ino, ".", ino, T_DIR)
            self._dir_add(ino, "..", dino, T_DIR)
            pinode = self.iget(dino)
            pinode.links += 1
            self.iput(dino, pinode)
        self._dir_add(dino, name, ino, typ)
        return ino

    # ------------------------------------------------------------ interfaz VFS
    def open(self, parts, flags):
        try:
            ino = self._walk(parts)
            if flags & O_CREAT and flags & O_EXCL:
                raise KError(EEXIST)
        except KError as e:
            if e.errno != ENOENT or not flags & O_CREAT:
                raise
            ino = self._create(parts, T_FILE)
        inode = self.iget(ino)
        if inode.mode == T_DIR:
            raise KError(EISDIR)
        if flags & O_TRUNC and (flags & O_ACCMODE) != O_RDONLY:
            self.truncate(ino, 0)
        return PyFile(self, ino)

    def stat(self, parts) -> dict:
        ino = self._walk(parts)
        i = self.iget(ino)
        return {"type": TYPE_NAMES.get(i.mode, "?"), "size": i.size, "ino": ino,
                "links": i.links, "mtime": i.mtime, "ctime": i.ctime, "fs": self.name}

    def readdir(self, parts) -> list:
        ino = self._walk(parts)
        if self.iget(ino).mode != T_DIR:
            raise KError(ENOTDIR)
        return [(n, TYPE_NAMES.get(t, "?")) for _, _, n, t in self._dir_iter(ino) if n not in (".", "..")]

    def mkdir(self, parts) -> None:
        self._create(parts, T_DIR)

    def unlink(self, parts) -> None:
        dino, name = self._parent(parts)
        ino = self._dir_lookup(dino, name)
        if not ino:
            raise KError(ENOENT)
        inode = self.iget(ino)
        if inode.mode == T_DIR:
            raise KError(EISDIR)
        self._dir_remove(dino, name)
        inode.links -= 1
        self.iput(ino, inode)
        if inode.links <= 0:
            if self.open_counts.get(ino):
                self.orphans.add(ino)
            else:
                self._free_inode(ino)

    def rmdir(self, parts) -> None:
        dino, name = self._parent(parts)
        if name in (".", ".."):
            raise KError(EINVAL)
        ino = self._dir_lookup(dino, name)
        if not ino:
            raise KError(ENOENT)
        if self.iget(ino).mode != T_DIR:
            raise KError(ENOTDIR)
        if any(n not in (".", "..") for _, _, n, _ in self._dir_iter(ino)):
            raise KError(ENOTEMPTY)
        self._dir_remove(dino, name)
        self._free_inode(ino)
        pinode = self.iget(dino)
        pinode.links -= 1
        self.iput(dino, pinode)

    def rename(self, a, b) -> None:
        if not a or not b:
            raise KError(EBUSY)
        if b[:len(a)] == a and len(b) > len(a):
            raise KError(EINVAL, "no se puede mover un directorio dentro de sí mismo")
        if a == b:
            return
        sdir, sname = self._parent(a)
        ino = self._dir_lookup(sdir, sname)
        if not ino:
            raise KError(ENOENT)
        ddir, dname = self._parent(b)
        check_name(dname)
        typ = self.iget(ino).mode
        existing = self._dir_lookup(ddir, dname)
        if existing:
            etyp = self.iget(existing).mode
            if etyp == T_DIR:
                if typ != T_DIR:
                    raise KError(EISDIR)
                self.rmdir(b)
            else:
                if typ == T_DIR:
                    raise KError(ENOTDIR)
                self.unlink(b)
        self._dir_remove(sdir, sname)
        self._dir_add(ddir, dname, ino, typ)
        if typ == T_DIR and sdir != ddir:
            self._dir_set_parent(ino, ddir)
            for d, delta in ((sdir, -1), (ddir, +1)):
                inode = self.iget(d)
                inode.links += delta
                self.iput(d, inode)

    def statfs(self) -> dict:
        s = self.sb
        return {"block_size": BLOCK, "blocks": s["total_blocks"], "free_blocks": s["free_blocks"],
                "inodes": s["inode_count"], "free_inodes": s["free_inodes"]}

    # ------------------------------------------------------------ fsck
    def fsck(self, repair: bool = True) -> dict:
        s = self.sb
        used_ino = {0, ROOT_INO}
        used_blk = set(range(s["data_start"]))
        refs: dict = {}
        report = {"bad_entries": 0, "block_bitmap": 0, "inode_bitmap": 0, "links": 0}
        stack, seen = [ROOT_INO], set()
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            for off, ino, name, _t in list(self._dir_iter(d)):
                if not 0 < ino < s["inode_count"] or self.iget(ino).mode == T_FREE:
                    report["bad_entries"] += 1
                    if repair:
                        self._write_inode(d, self.iget(d), off, bytes(DIRENT))
                    continue
                refs[ino] = refs.get(ino, 0) + 1
                if name in (".", ".."):
                    continue
                used_ino.add(ino)
                if self.iget(ino).mode == T_DIR:
                    stack.append(ino)
        for ino in used_ino - {0}:
            used_blk.update(self._blocks(self.iget(ino)))
            inode = self.iget(ino)
            if inode.links != refs.get(ino, 0):
                report["links"] += 1
                if repair:
                    inode.links = refs.get(ino, 0)
                    self.iput(ino, inode)
        for n in range(s["total_blocks"]):
            want = 1 if n in used_blk else 0
            if self._bit_get(s["bbmap_start"], n) != want:
                report["block_bitmap"] += 1
                if repair:
                    self._bit_set(s["bbmap_start"], n, want)
        for n in range(s["inode_count"]):
            want = 1 if n in used_ino else 0
            if self._bit_get(s["ibmap_start"], n) != want:
                report["inode_bitmap"] += 1
                if repair:
                    self._bit_set(s["ibmap_start"], n, want)
                    if not want:
                        self.iput(n, Inode())
        if repair:
            s["free_blocks"] = s["total_blocks"] - len(used_blk)
            s["free_inodes"] = s["inode_count"] - len(used_ino)
            self.sync()
        report["errors"] = sum(report.values())
        return report
