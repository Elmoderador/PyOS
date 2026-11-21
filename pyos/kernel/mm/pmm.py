"""Gestor de memoria física: asignador de marcos de 4 KiB.

El mapa de marcos (1 byte por marco: 0 libre, 1 usado) vive DENTRO de la RAM
física, a partir de 0x1000, y sus propios marcos quedan reservados.
El marco 0 se reserva para que la dirección física 0 nunca sea válida.
"""

from ..errors import KernelPanic

PAGE_SIZE = 4096
PAGE_SHIFT = 12
BITMAP_BASE = PAGE_SIZE


class OutOfMemory(Exception):
    pass


class FrameAllocator:
    def __init__(self, ram):
        self.ram = ram
        self.nframes = ram.size // PAGE_SIZE
        bitmap_frames = (self.nframes + PAGE_SIZE - 1) // PAGE_SIZE
        self.reserved = 1 + bitmap_frames
        if self.reserved >= self.nframes:
            raise KernelPanic("RAM insuficiente para el mapa de marcos")
        ram.fill(BITMAP_BASE, self.nframes, 0)
        ram.fill(BITMAP_BASE, self.reserved, 1)  # marcos 0..reserved-1 usados
        self.free_count = self.nframes - self.reserved
        self._next = self.reserved
        self.allocs = 0
        self.frees = 0

    def _get(self, pfn: int) -> int:
        return self.ram.read(BITMAP_BASE + pfn, 1)[0]

    def alloc(self, zero: bool = True) -> int:
        if self.free_count == 0:
            raise OutOfMemory("sin marcos físicos libres")
        end = BITMAP_BASE + self.nframes
        idx = self.ram.find_byte(0, BITMAP_BASE + self._next, end)
        if idx < 0:
            idx = self.ram.find_byte(0, BITMAP_BASE + self.reserved, end)
        if idx < 0:  # pragma: no cover - free_count y bitmap desincronizados
            raise KernelPanic("PMM: free_count > 0 pero el bitmap está lleno")
        pfn = idx - BITMAP_BASE
        self.ram.write(idx, b"\x01")
        self.free_count -= 1
        self.allocs += 1
        self._next = pfn + 1 if pfn + 1 < self.nframes else self.reserved
        if zero:
            self.ram.fill(pfn * PAGE_SIZE, PAGE_SIZE, 0)
        return pfn

    def free(self, pfn: int) -> None:
        if not self.reserved <= pfn < self.nframes:
            raise KernelPanic(f"PMM: free de marco inválido/reservado {pfn}")
        if self._get(pfn) != 1:
            raise KernelPanic(f"PMM: doble liberación del marco {pfn}")
        self.ram.write(BITMAP_BASE + pfn, b"\x00")
        self.free_count += 1
        self.frees += 1

    def is_used(self, pfn: int) -> bool:
        return self._get(pfn) == 1

    @property
    def total_bytes(self) -> int:
        return self.nframes * PAGE_SIZE

    @property
    def free_bytes(self) -> int:
        return self.free_count * PAGE_SIZE
