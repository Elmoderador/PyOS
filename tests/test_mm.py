import pytest

from pyos.hal.emulated import RAM
from pyos.kernel.errors import KernelPanic
from pyos.kernel.mm.pmm import BITMAP_BASE, FrameAllocator, OutOfMemory
from pyos.kernel.mm.vmm import (HEAP_BASE, MMAP_BASE, PROT_READ, PROT_WRITE, USER_TOP,
                                AddressSpace, MapError, SegmentationFault)


@pytest.fixture
def pmm():
    return FrameAllocator(RAM(1 << 20))  # 256 marcos


def test_bitmap_vive_en_ram(pmm):
    pfn = pmm.alloc()
    assert pmm.ram.read(BITMAP_BASE + pfn, 1) == b"\x01"
    pmm.free(pfn)
    assert pmm.ram.read(BITMAP_BASE + pfn, 1) == b"\x00"


def test_agotamiento_y_doble_free(pmm):
    frames = [pmm.alloc(zero=False) for _ in range(pmm.free_count)]
    assert len(set(frames)) == len(frames)
    with pytest.raises(OutOfMemory):
        pmm.alloc()
    pmm.free(frames[0])
    with pytest.raises(KernelPanic):
        pmm.free(frames[0])
    with pytest.raises(KernelPanic):
        pmm.free(0)  # marco reservado


def test_paginacion_bajo_demanda(pmm):
    a = AddressSpace(pmm)
    free0 = pmm.free_count
    a.map(MMAP_BASE, 16 * 4096, PROT_READ | PROT_WRITE, "anon")
    assert pmm.free_count == free0 and a.rss == 0      # mapear no asigna marcos
    a.write(MMAP_BASE + 4090, b"cruza-pagina")          # escritura que cruza dos páginas
    assert a.rss == 2
    assert a.read(MMAP_BASE + 4090, 12) == b"cruza-pagina"
    assert a.read(MMAP_BASE + 8 * 4096, 4) == b"\0" * 4  # página nueva, a cero


def test_protecciones(pmm):
    a = AddressSpace(pmm)
    a.map(MMAP_BASE, 4096, PROT_READ, "ro")
    with pytest.raises(SegmentationFault):
        a.write(MMAP_BASE, b"x")
    with pytest.raises(SegmentationFault):
        a.read(0x1000, 1)                   # no mapeado
    with pytest.raises(SegmentationFault):
        a.read(USER_TOP, 1)                 # espacio del kernel
    a.map(MMAP_BASE + 4096, 4096, PROT_READ | PROT_WRITE, "rw")
    a.write(MMAP_BASE + 4096, b"ok")
    a.protect(MMAP_BASE + 4096, 4096, PROT_READ)
    with pytest.raises(SegmentationFault):
        a.write(MMAP_BASE + 4096, b"no")
    with pytest.raises(MapError):
        a.map(MMAP_BASE, 4096, PROT_READ, "solapa")


def test_sbrk_y_destroy_devuelven_todo(pmm):
    before = pmm.free_count
    a = AddressSpace(pmm)
    base = a.sbrk(10 * 4096)
    assert base == HEAP_BASE
    for i in range(10):
        a.write(base + i * 4096, b"z")
    assert a.rss == 10
    a.sbrk(-6 * 4096)
    assert a.rss == 4
    with pytest.raises(SegmentationFault):
        a.read(base + 5 * 4096, 1)
    a.unmap(base, 4096)
    assert a.rss == 3
    a.destroy()
    assert pmm.free_count == before
