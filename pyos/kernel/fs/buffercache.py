"""Caché de bloques (buffer cache) con write-back y expulsión LRU."""

from collections import OrderedDict

SECTOR = 512


class BufferCache:
    def __init__(self, disk, base_lba: int, block_size: int, nblocks: int, capacity: int = 512):
        self.disk = disk
        self.base = base_lba
        self.bs = block_size
        self.spb = block_size // SECTOR
        self.nblocks = nblocks
        self.capacity = capacity
        self._c: OrderedDict = OrderedDict()
        self._dirty: set = set()
        self.hits = self.misses = self.writebacks = 0

    def _check(self, blk: int) -> None:
        if not 0 <= blk < self.nblocks:
            raise ValueError(f"bloque fuera de rango: {blk}")

    def read(self, blk: int) -> bytearray:
        """Devuelve el buffer mutable del bloque. Tras modificarlo, llamar a put()."""
        self._check(blk)
        buf = self._c.get(blk)
        if buf is not None:
            self.hits += 1
            self._c.move_to_end(blk)
            return buf
        self.misses += 1
        buf = bytearray(self.disk.read(self.base + blk * self.spb, self.spb))
        self._insert(blk, buf)
        return buf

    def put(self, blk: int, buf) -> None:
        self._check(blk)
        if len(buf) != self.bs:
            raise ValueError("tamaño de bloque incorrecto")
        if not isinstance(buf, bytearray):
            buf = bytearray(buf)
        self._insert(blk, buf)
        self._dirty.add(blk)

    def _insert(self, blk: int, buf: bytearray) -> None:
        self._c[blk] = buf
        self._c.move_to_end(blk)
        while len(self._c) > self.capacity:
            old, obuf = self._c.popitem(last=False)
            if old in self._dirty:
                self._writeback(old, obuf)

    def _writeback(self, blk: int, buf) -> None:
        self.disk.write(self.base + blk * self.spb, bytes(buf))
        self._dirty.discard(blk)
        self.writebacks += 1

    def sync(self) -> int:
        n = 0
        for blk in sorted(self._dirty):
            self._writeback(blk, self._c[blk])
            n += 1
        self.disk.flush()
        return n

    def invalidate(self) -> None:
        self._c.clear()
        self._dirty.clear()

    @property
    def dirty_count(self) -> int:
        return len(self._dirty)
