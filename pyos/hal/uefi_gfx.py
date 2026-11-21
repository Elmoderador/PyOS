"""Gráficos y ratón reales para la HAL UEFI (sin GOP: Python no puede llamar a protocolos).

Pantalla
--------
Se usa el modo que ya dejó puesto el firmware (GOP) y se escribe directamente en el
framebuffer lineal del adaptador de vídeo:

* Bochs/QEMU std-VGA, VBoxVGA y VBoxSVGA: registros VBE "DISPI" en los puertos
  0x1CE/0x1CF (resolución, bpp, ancho virtual) + BAR de memoria del dispositivo PCI.
* VMware SVGA II (QEMU -vga vmware, VMSVGA de VirtualBox): registros SVGA por el BAR
  de E/S (índice/valor) con FB_START/FB_OFFSET/BYTES_PER_LINE.

Solo 32 bpp (XRGB8888).

Copia rápida
------------
edk2.writemem_dword escribe 4 bytes por llamada (lento). edk2.writemem tiene un fallo en
edk2-libc (formato "s#" con PY_SSIZE_T_CLEAN volcado sobre un 'int'): el tamaño de 64
bits pisa la mitad baja del puntero al búfer, así que en la práctica copia
**desde la dirección física 0** (los objetos de Python están por debajo de 4 GiB) hacia
el destino pedido, con la longitud correcta. Es determinista (mismo binario siempre), y
PyOS lo usa como memcpy desde una página de trabajo:

* la página física 0 (en UEFI es la página "nula": la reserva el núcleo DXE para cazar
  punteros nulos y nadie la usa) se guarda al empezar y se restaura al terminar;
* se rellena con un color por duplicación (1 + log2(n) llamadas) y luego cada tramo
  horizontal de ese color es UNA llamada, sea del tamaño que sea (hasta 1024 píxeles).

Antes de usarlo se comprueba con una autoprueba en RAM reservada. Si el firmware no se
comporta así (otro binario, puntero por encima de 4 GiB...) se usa el camino lento,
píxel a píxel, que siempre funciona.
"""
import edk2

SCRATCH_PX = 1024              # página 0: 4096 bytes = 1024 píxeles de 32 bits


def _io_w(port, size, val):
    edk2.writeio(port, size, val)


def _io_r(port, size):
    return edk2.readio(port, size)


def _pci(bus, dev, fn, off):
    return edk2.readpci(bus, dev, fn, off, 4)


def _mem_bars(bus, dev, fn):
    """BARs de memoria (dirección, prefetchable) del dispositivo."""
    bars = []
    i = 0
    while i < 6:
        v = _pci(bus, dev, fn, 0x10 + 4 * i)
        if v & 1:                                   # BAR de E/S
            i += 1
            continue
        kind = (v >> 1) & 3
        addr = v & 0xFFFFFFF0
        if kind == 2:                               # 64 bits
            addr |= _pci(bus, dev, fn, 0x14 + 4 * i) << 32
            i += 1
        if addr:
            bars.append((addr, bool(v & 8)))
        i += 1
    return bars


def _io_bar(bus, dev, fn):
    for i in range(6):
        v = _pci(bus, dev, fn, 0x10 + 4 * i)
        if v & 1:
            return v & 0xFFFC
    return None


class GfxError(Exception):
    pass


def detect(pci_devices):
    """Devuelve (descripción, base, ancho, alto, pitch_bytes) del modo activo."""
    displays = [d for d in pci_devices if (d[5] >> 16) == 0x03]
    if not displays:
        raise GfxError("no hay ningún adaptador de vídeo PCI")
    # 1) VMware SVGA II
    for bus, dev, fn, ven, did, cls in displays:
        if ven == 0x15AD and did == 0x0405:
            port = _io_bar(bus, dev, fn)
            if port is None:
                continue

            def reg(i):
                _io_w(port, 4, i)
                return _io_r(port + 1, 4)
            _io_w(port, 4, 0)
            _io_w(port + 1, 4, 0x90000002)                # SVGA_ID_2
            if reg(0) & 0xFF != 2 or not reg(1):          # versión y SVGA_REG_ENABLE
                continue
            w, h, bpp, pitch = reg(2), reg(3), reg(7), reg(12)
            base = reg(13) + reg(14)
            if bpp != 32:
                raise GfxError("VMware SVGA en %d bpp (LOOK necesita 32)" % bpp)
            return ("VMware SVGA II", base, w, h, pitch)
    # 2) Bochs DISPI (QEMU std-VGA, VBoxVGA, VBoxSVGA)
    _io_w(0x1CE, 2, 0)
    vid = _io_r(0x1CF, 2)
    if 0xB0C0 <= vid <= 0xB0CF:
        def dispi(i):
            _io_w(0x1CE, 2, i)
            return _io_r(0x1CF, 2)
        enabled = dispi(4)
        if enabled & 1:
            w, h, bpp, vw = dispi(1), dispi(2), dispi(3), dispi(6)
            if bpp != 32:
                raise GfxError("modo VBE en %d bpp (LOOK necesita 32)" % bpp)
            for bus, dev, fn, ven, did, cls in displays:
                bars = _mem_bars(bus, dev, fn)
                pref = [a for a, p in bars if p] or [a for a, p in bars]
                if pref:
                    name = {0x1234: "Bochs/QEMU std-VGA", 0x80EE: "VirtualBox VBoxVGA/VBoxSVGA",
                            0x15AD: "VMware SVGA en modo VBE"}.get(
                        ven, "VBE DISPI %04x:%04x" % (ven, did))
                    return (name + " (VBE %x)" % vid, pref[0], w, h, max(vw, w) * 4)
    ids = ", ".join("%04x:%04x" % (d[3], d[4]) for d in displays)
    raise GfxError("adaptador de vídeo no soportado (%s). En VirtualBox usa el "
                   "controlador gráfico VBoxSVGA o VBoxVGA." % ids)


class LinearFramebuffer(object):
    """Framebuffer lineal XRGB8888 en memoria física."""

    def __init__(self, desc, base, width, height, pitch):
        self.desc = desc
        self.base = base
        self.width = width
        self.height = height
        self.pitch = pitch
        self.fast = False
        self._saved0 = None
        self._sc_color = None
        self._sc_len = 0
        self._dummy = {}
        self.calls = 0

    # ------------------------------------------------------------ ciclo de vida
    def begin(self):
        self._saved0 = edk2.readmem(0, 0, 4096)
        self.fast = self._selftest()
        self._sc_color = None
        self._sc_len = 0

    def end(self):
        if self._saved0 is not None:
            s = self._saved0
            for i in range(0, 4096, 4):
                edk2.writemem_dword(i, 0, s[i] | (s[i + 1] << 8) | (s[i + 2] << 16) | (s[i + 3] << 24))
            self._saved0 = None
        self.fast = False

    def _selftest(self):
        """¿writemem copia desde la página 0? Se comprueba en RAM propia, no en pantalla."""
        try:
            va = edk2.allocphysmem(4096, 0xFFFFFFFF)
            va = va[0] if isinstance(va, tuple) else va
            if not va:
                return False
            lo, hi = va & 0xFFFFFFFF, va >> 32
            pat = (0x13572468, 0x0BADF00D, 0x7E57C0DE, 0x2468ACE0)
            for i, v in enumerate(pat):
                edk2.writemem_dword(4 * i, 0, v)
                edk2.writemem_dword(lo + 4 * i, hi, 0)
            edk2.writemem(lo, hi, self._d(16))
            ok = all(edk2.readmem_dword(lo + 4 * i, hi) == v for i, v in enumerate(pat))
            # y la longitud se respeta: el dword siguiente no se toca
            edk2.writemem_dword(lo + 16, hi, 0x55555555)
            edk2.writemem(lo, hi, self._d(8))
            ok = ok and edk2.readmem_dword(lo + 16, hi) == 0x55555555
            return ok
        except Exception:
            return False

    def _d(self, n):
        d = self._dummy.get(n)
        if d is None:
            d = self._dummy[n] = bytes(n)
        return d

    # ------------------------------------------------------------ primitivas
    def _scratch(self, rgb, n):
        if self._sc_color != rgb:
            edk2.writemem_dword(0, 0, rgb)
            self._sc_color = rgb
            self._sc_len = 1
        L = self._sc_len
        while L < n:
            m = min(L, n - L)
            edk2.writemem(4 * L, 0, self._d(4 * m))    # [0, m) -> [L, L+m): sin solape
            L += m
            self.calls += 1
        self._sc_len = L

    def span(self, x, y, n, rgb):
        addr = self.base + y * self.pitch + 4 * x
        if self.fast:
            while n > 0:
                k = n if n < SCRATCH_PX else SCRATCH_PX
                self._scratch(rgb, k)
                edk2.writemem(addr & 0xFFFFFFFF, addr >> 32, self._d(4 * k))
                self.calls += 1
                addr += 4 * k
                n -= k
        else:
            hi = addr >> 32
            lo = addr & 0xFFFFFFFF
            for i in range(n):
                edk2.writemem_dword(lo + 4 * i, hi, rgb)
            self.calls += n

    def spans(self, items, rgb):
        """Varios tramos (x, y, n) del mismo color: el relleno de la página se amortiza."""
        for x, y, n in items:
            self.span(x, y, n, rgb)

    def pixels(self, x, y, rgbs):
        addr = self.base + y * self.pitch + 4 * x
        lo, hi = addr & 0xFFFFFFFF, addr >> 32
        for i, c in enumerate(rgbs):
            edk2.writemem_dword(lo + 4 * i, hi, c)
        self.calls += len(rgbs)

    def read(self, x, y, n):
        addr = self.base + y * self.pitch + 4 * x
        b = edk2.readmem(addr & 0xFFFFFFFF, addr >> 32, 4 * n)
        return [b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) for i in range(0, 4 * n, 4)]

    def info(self):
        return {"adapter": self.desc, "width": self.width, "height": self.height,
                "base": "0x%x" % self.base, "pitch": self.pitch,
                "copy": "rápida (writemem desde la página 0)" if self.fast else "lenta (dword a dword)"}


# ---------------------------------------------------------------------- i8042
class I8042(object):
    """Controlador i8042 compartido: separa los bytes del teclado y del ratón (AUX)."""

    def __init__(self):
        st = _io_r(0x64, 1)
        self.present = st != 0xFF
        self.kbd_q = []
        self.aux_q = []
        self.mouse_on = False
        self.packet_size = 3
        self.wheel = False
        if self.present:
            self.poll()
            self.kbd_q = []
            self.aux_q = []

    def poll(self):
        n = 0
        while n < 64:
            st = _io_r(0x64, 1)
            if not st & 1:
                break
            b = _io_r(0x60, 1)
            (self.aux_q if st & 0x20 else self.kbd_q).append(b)
            n += 1

    # API del teclado
    def read_scancode(self):
        if not self.kbd_q:
            self.poll()
        return self.kbd_q.pop(0) if self.kbd_q else None

    # ratón
    def _wait_in(self):
        for _ in range(20000):
            if not _io_r(0x64, 1) & 2:
                return True
        return False

    def _cmd(self, b):
        self._wait_in()
        _io_w(0x64, 1, b)

    def _aux(self, b, clock):
        self._cmd(0xD4)
        self._wait_in()
        _io_w(0x60, 1, b)
        t0 = clock()
        while clock() - t0 < 0.2:
            self.poll()
            if self.aux_q:
                r = self.aux_q.pop(0)
                if r == 0xFA:
                    return True
                if r == 0xFE:
                    return False
        return False

    def mouse_enable(self, clock):
        if self.mouse_on:
            return True
        if not self.present:
            return False
        self.poll()                           # vacía lo pendiente (va a sus colas)
        self._cmd(0xA8)                       # habilita el puerto AUX
        self.poll()
        self._cmd(0x20)                       # lee el byte de configuración
        cfg = None
        t0 = clock()
        while clock() - t0 < 0.1:
            st = _io_r(0x64, 1)
            if st & 1:
                cfg = _io_r(0x60, 1)
                break
        if cfg is not None:
            # relojes de teclado (bit 4) y ratón (bit 5) activos; el resto como estaba
            self._cmd(0x60)
            self._wait_in()
            _io_w(0x60, 1, cfg & ~0x30 & 0xFF)
        self._cmd(0xAE)                       # teclado habilitado (por si acaso)
        ok = self._aux(0xF6, clock)           # valores por defecto
        if ok:
            self._intellimouse(clock)
            ok = self._aux(0xF4, clock)       # empezar a informar
        self.aux_q = []
        self.mouse_on = ok
        return ok

    def _intellimouse(self, clock):
        """Secuencia mágica de Microsoft (frecuencia 200, 100, 80): si el ratón responde con
        ID 3 pasa a paquetes de 4 bytes con la rueda en el cuarto."""
        for rate in (200, 100, 80):
            if not (self._aux(0xF3, clock) and self._aux(rate, clock)):
                return False
        if not self._aux(0xF2, clock):        # leer ID
            return False
        t0 = clock()
        while clock() - t0 < 0.2:
            self.poll()
            if self.aux_q:
                ident = self.aux_q.pop(0)
                self.wheel = ident in (3, 4)
                self.packet_size = 4 if self.wheel else 3
                break
        self._aux(0xF3, clock) and self._aux(100, clock)   # frecuencia normal
        return self.wheel

    def mouse_disable(self, clock):
        if self.mouse_on:
            self._aux(0xF5, clock)
            self.aux_q = []
            self.mouse_on = False

    def mouse_bytes(self):
        self.poll()
        q = self.aux_q
        self.aux_q = []
        return q
