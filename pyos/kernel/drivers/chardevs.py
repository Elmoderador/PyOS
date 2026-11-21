"""Dispositivos de carácter simples: null, zero, random, hda (disco crudo, solo lectura)."""

from ..errors import KError, EROFS
from ..fs.vfs import FileOps
from .devices import CharDevice


class _NullOps(FileOps):
    seekable = False

    def read(self, of, n):
        return b""

    def write(self, of, data):
        return len(data)


class _ZeroOps(_NullOps):
    def read(self, of, n):
        return bytes(min(n, 65536))


class _RandomOps(_NullOps):
    def __init__(self, source):
        self.source = source

    def read(self, of, n):
        return self.source(min(n, 65536))


class NullDevice(CharDevice):
    name, major, minor, description = "null", 1, 3, "sumidero"

    def open(self, flags):
        return _NullOps()


class ZeroDevice(CharDevice):
    name, major, minor, description = "zero", 1, 5, "fuente de ceros"

    def open(self, flags):
        return _ZeroOps()


class RandomDevice(CharDevice):
    name, major, minor = "random", 1, 8

    def __init__(self, source, description):
        self.source = source
        self.description = description

    def open(self, flags):
        return _RandomOps(self.source)


class _DiskOps(FileOps):
    def __init__(self, disk):
        self.disk = disk

    def size(self):
        return self.disk.sectors * 512

    def read(self, of, n):
        n = max(0, min(n, self.size() - of.offset, 1 << 20))
        if n == 0:
            return b""
        first = of.offset // 512
        last = (of.offset + n - 1) // 512
        raw = self.disk.read(first, last - first + 1)
        skip = of.offset - first * 512
        data = raw[skip:skip + n]
        of.offset += len(data)
        return data

    def write(self, of, data):
        raise KError(EROFS, "/dev/hda es de solo lectura (protege al FS montado)")


class DiskDevice(CharDevice):
    name, major, minor, description = "hda", 3, 0, "disco ATA (acceso crudo, solo lectura)"

    def __init__(self, disk):
        self.disk = disk

    def open(self, flags):
        return _DiskOps(self.disk)
