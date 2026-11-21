"""Memoria virtual: paginación de dos niveles (estilo x86 de 32 bits).

- Directorio de páginas y tablas de páginas almacenados en la RAM física.
- Direcciones virtuales de 32 bits: 10 bits PDE | 10 bits PTE | 12 bits offset.
- Regiones (VMA) con protección R/W/X; paginación bajo demanda (marcos a cero
  asignados en el fallo de página); flags Accessed/Dirty mantenidos por la MMU.
- Todo acceso de usuario pasa por la MMU software (`translate`).
"""

from .pmm import PAGE_SIZE, OutOfMemory  # noqa: F401  (re-export)

PTE_P, PTE_W, PTE_U, PTE_A, PTE_D = 0x1, 0x2, 0x4, 0x20, 0x40
PROT_NONE, PROT_READ, PROT_WRITE, PROT_EXEC = 0, 1, 2, 4

USER_BASE = 0x00400000
TEXT_BASE = 0x00400000
HEAP_BASE = 0x10000000
MMAP_BASE = 0x40000000
USER_TOP = 0xC0000000      # por encima: espacio del kernel (no mapeable por usuario)
MAX_ACCESS = 16 * 1024 * 1024


def page_up(n: int) -> int:
    return (n + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)


class PageFault(Exception):
    def __init__(self, vaddr: int, write: bool, present: bool):
        super().__init__(f"#PF {vaddr:#010x} {'W' if write else 'R'} {'P' if present else 'NP'}")
        self.vaddr, self.write, self.present = vaddr, write, present


class SegmentationFault(Exception):
    def __init__(self, vaddr: int, reason: str):
        super().__init__(f"violación de segmento en {vaddr:#010x}: {reason}")
        self.vaddr, self.reason = vaddr, reason


class MapError(Exception):
    pass


class VMA(object):
    __slots__ = ("start", "end", "prot", "name")

    def __init__(self, start, end, prot, name):
        self.start, self.end, self.prot, self.name = start, end, prot, name

    def flags_str(self) -> str:
        return "".join(c if self.prot & b else "-" for c, b in
                       (("r", PROT_READ), ("w", PROT_WRITE), ("x", PROT_EXEC)))


class AddressSpace:
    def __init__(self, pmm, fault_handler=None):
        self.pmm = pmm
        self.ram = pmm.ram
        self.pgdir = pmm.alloc()
        self.pt_pages = 1
        self.rss = 0
        self.faults = 0
        self.vmas = []
        self.brk_base = self.brk = HEAP_BASE
        self.fault_handler = fault_handler or self.handle_fault
        self.destroyed = False

    # ---------------------------------------------------------------- MMU
    def _pte_addr(self, va: int, create: bool):
        pde_addr = self.pgdir * PAGE_SIZE + ((va >> 22) & 0x3FF) * 4
        pde = self.ram.read_u32(pde_addr)
        if not pde & PTE_P:
            if not create:
                return None
            pt = self.pmm.alloc(zero=True)
            pde = (pt << 12) | PTE_P | PTE_W | PTE_U
            self.ram.write_u32(pde_addr, pde)
            self.pt_pages += 1
        return (pde >> 12) * PAGE_SIZE + ((va >> 12) & 0x3FF) * 4

    def translate(self, va: int, write: bool = False) -> int:
        """Dirección virtual -> física. Lanza PageFault como lo haría la MMU."""
        pte_addr = self._pte_addr(va, False)
        pte = self.ram.read_u32(pte_addr) if pte_addr is not None else 0
        if not pte & PTE_P:
            raise PageFault(va, write, False)
        if write and not pte & PTE_W:
            raise PageFault(va, write, True)
        new = pte | PTE_A | (PTE_D if write else 0)
        if new != pte:
            self.ram.write_u32(pte_addr, new)
        return (pte >> 12) * PAGE_SIZE + (va & 0xFFF)

    def find_vma(self, va: int):
        for v in self.vmas:
            if v.start <= va < v.end:
                return v
        return None

    def handle_fault(self, pf: PageFault) -> None:
        """Manejador de #PF: paginación bajo demanda o violación de segmento."""
        self.faults += 1
        vma = self.find_vma(pf.vaddr)
        if vma is None:
            raise SegmentationFault(pf.vaddr, "dirección no mapeada")
        if pf.write and not vma.prot & PROT_WRITE:
            raise SegmentationFault(pf.vaddr, f"escritura en región '{vma.name}' de solo lectura")
        if not pf.write and not vma.prot & PROT_READ:
            raise SegmentationFault(pf.vaddr, f"lectura de región '{vma.name}' sin permiso")
        if pf.present:  # pragma: no cover - sin COW no debería ocurrir
            raise SegmentationFault(pf.vaddr, "fallo de protección")
        pfn = self.pmm.alloc(zero=True)  # OutOfMemory se propaga -> OOM killer
        flags = PTE_P | PTE_U | (PTE_W if vma.prot & PROT_WRITE else 0)
        self.ram.write_u32(self._pte_addr(pf.vaddr, True), (pfn << 12) | flags)
        self.rss += 1

    # ---------------------------------------------------------------- regiones
    def _check(self, start: int, length: int) -> int:
        if start % PAGE_SIZE or length <= 0:
            raise MapError("rango no alineado o vacío")
        length = page_up(length)
        if start < USER_BASE or start + length > USER_TOP:
            raise MapError("rango fuera del espacio de usuario")
        return length

    def map(self, start: int, length: int, prot: int, name: str) -> VMA:
        length = self._check(start, length)
        end = start + length
        for v in self.vmas:
            if v.start < end and start < v.end:
                raise MapError(f"solapa con '{v.name}'")
        vma = VMA(start, end, prot, name)
        self.vmas.append(vma)
        self.vmas.sort(key=lambda v: v.start)
        return vma

    def find_free(self, length: int, base: int = MMAP_BASE) -> int:
        length = page_up(length)
        start = base
        for v in self.vmas:
            if v.end <= start:
                continue
            if v.start >= start + length:
                break
            start = v.end
        if start + length > USER_TOP:
            raise MapError("espacio de direcciones agotado")
        return start

    def _release(self, start: int, end: int) -> None:
        va = start
        while va < end:
            pte_addr = self._pte_addr(va, False)
            if pte_addr is None:  # sin tabla de páginas: salta al siguiente bloque de 4 MiB
                va = ((va >> 22) + 1) << 22
                continue
            pte = self.ram.read_u32(pte_addr)
            if pte & PTE_P:
                self.pmm.free(pte >> 12)
                self.ram.write_u32(pte_addr, 0)
                self.rss -= 1
            va += PAGE_SIZE

    def _split_out(self, start: int, end: int):
        """Recorta [start,end) de las VMAs. Devuelve las partes eliminadas."""
        keep, removed = [], []
        for v in self.vmas:
            if v.end <= start or v.start >= end:
                keep.append(v)
                continue
            if v.start < start:
                keep.append(VMA(v.start, start, v.prot, v.name))
            if v.end > end:
                keep.append(VMA(end, v.end, v.prot, v.name))
            removed.append(VMA(max(v.start, start), min(v.end, end), v.prot, v.name))
        keep.sort(key=lambda v: v.start)
        self.vmas = keep
        return removed

    def unmap(self, start: int, length: int) -> None:
        length = self._check(start, length)
        for part in self._split_out(start, start + length):
            self._release(part.start, part.end)

    def protect(self, start: int, length: int, prot: int) -> None:
        length = self._check(start, length)
        end = start + length
        covered = sum(min(v.end, end) - max(v.start, start)
                      for v in self.vmas if v.start < end and start < v.end)
        if covered != length:
            raise MapError("mprotect sobre rango no mapeado")
        parts = self._split_out(start, end)
        for p in parts:
            p.prot = prot
            self.vmas.append(p)
            va = p.start
            while va < p.end:
                pte_addr = self._pte_addr(va, False)
                if pte_addr is not None:
                    pte = self.ram.read_u32(pte_addr)
                    if pte & PTE_P:
                        pte = (pte | PTE_W) if prot & PROT_WRITE else (pte & ~PTE_W)
                        self.ram.write_u32(pte_addr, pte)
                va += PAGE_SIZE
        self.vmas.sort(key=lambda v: v.start)

    def sbrk(self, incr: int) -> int:
        old = self.brk
        new = old + incr
        if new < self.brk_base:
            raise MapError("brk por debajo de la base del heap")
        old_top, new_top = page_up(old), page_up(new)
        if new_top > old_top:
            heap = self.find_vma(self.brk_base) if old_top > self.brk_base else None
            for v in self.vmas:
                if v is not heap and v.start < new_top and old_top < v.end:
                    raise MapError("el heap chocaría con otra región")
            if heap is None:
                self.map(self.brk_base, new_top - self.brk_base, PROT_READ | PROT_WRITE, "heap")
            else:
                heap.end = new_top
        elif new_top < old_top:
            self.unmap(new_top, old_top - new_top)
        self.brk = new
        return old

    # ---------------------------------------------------------------- copia
    def _phys(self, va: int, write: bool) -> int:
        for _ in range(2):
            try:
                return self.translate(va, write)
            except PageFault as pf:
                self.fault_handler(pf)
        raise SegmentationFault(va, "fallo de página no resuelto")  # pragma: no cover

    def _span(self, va: int, n: int) -> None:
        if n < 0 or n > MAX_ACCESS:
            raise SegmentationFault(va, "tamaño de acceso inválido")
        if va < 0 or va + n > USER_TOP:
            raise SegmentationFault(va, "acceso al espacio del kernel")

    def read(self, va: int, n: int) -> bytes:
        self._span(va, n)
        out = bytearray()
        pos = 0
        while pos < n:
            cur = va + pos
            chunk = min(n - pos, PAGE_SIZE - (cur & 0xFFF))
            out += self.ram.read(self._phys(cur, False), chunk)
            pos += chunk
        return bytes(out)

    def write(self, va: int, data: bytes, force: bool = False) -> None:
        """force=True: escritura del cargador del kernel sobre páginas de solo lectura."""
        n = len(data)
        self._span(va, n)
        pos = 0
        while pos < n:
            cur = va + pos
            chunk = min(n - pos, PAGE_SIZE - (cur & 0xFFF))
            self.ram.write(self._phys(cur, not force), data[pos:pos + chunk])
            pos += chunk

    def clone(self):
        """Copia completa del espacio de direcciones (fork). Copia las páginas presentes."""
        child = AddressSpace(self.pmm)
        child.vmas = [VMA(v.start, v.end, v.prot, v.name) for v in self.vmas]
        child.brk_base, child.brk = self.brk_base, self.brk
        ps = PAGE_SIZE
        pd = self.ram.read(self.pgdir * ps, ps)
        for i in range(1024):
            pde = int.from_bytes(pd[i * 4:i * 4 + 4], "little")
            if not pde & PTE_P:
                continue
            raw = self.ram.read((pde >> 12) * ps, ps)
            for j in range(1024):
                pte = int.from_bytes(raw[j * 4:j * 4 + 4], "little")
                if not pte & PTE_P:
                    continue
                va = (i << 22) | (j << 12)
                pfn = self.pmm.alloc(zero=False)
                self.ram.write(pfn * ps, self.ram.read((pte >> 12) * ps, ps))
                child.ram.write_u32(child._pte_addr(va, True), (pfn << 12) | (pte & 0xFFF))
                child.rss += 1
        return child

    # ---------------------------------------------------------------- fin
    def destroy(self) -> None:
        if self.destroyed:
            return
        ps = PAGE_SIZE
        pd = self.ram.read(self.pgdir * ps, ps)
        for i in range(1024):
            pde = int.from_bytes(pd[i * 4:i * 4 + 4], "little")
            if not pde & PTE_P:
                continue
            pt = pde >> 12
            raw = self.ram.read(pt * ps, ps)
            for j in range(1024):
                pte = int.from_bytes(raw[j * 4:j * 4 + 4], "little")
                if pte & PTE_P:
                    self.pmm.free(pte >> 12)
            self.pmm.free(pt)
        self.pmm.free(self.pgdir)
        self.vmas.clear()
        self.rss = 0
        self.pt_pages = 0
        self.destroyed = True

    def maps(self) -> str:
        return "".join(f"{v.start:08x}-{v.end:08x} {v.flags_str()} {v.name}\n" for v in self.vmas)
