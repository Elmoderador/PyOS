"""HAL de hardware REAL: PyOS corriendo directamente sobre el firmware UEFI.

Todo lo de aquí habla con los chips de la máquina mediante el módulo `edk2`
del CPython para UEFI (puertos de E/S, memoria física, configuración PCI):

  - Temporizador ACPI PM (3,579545 MHz), localizado recorriendo el bus PCI.
  - Botón de encendido ACPI (PM1_STS.PWRBTN_STS).
  - Controlador de teclado i8042 / PS/2 (scancodes set 1).
  - UART 16550 (COM1).
  - RAM física reservada al firmware y accedida por direcciones físicas.

El firmware UEFI solo se usa para: pantalla (ConOut), el sistema de archivos
FAT donde vive la imagen de disco de PyOS y el apagado/reinicio.
"""
import os
import sys
import time

import edk2  # módulo del CPython para UEFI (edk2-libc)

from . import MachineCheck

SECTOR = 512
PM_HZ = 3579545
KNOWN_ACPI = {
    0x71138086: ("Intel PIIX4 ACPI", 0x40),
    0x29188086: ("Intel ICH9 LPC", 0x40),
}


# ------------------------------------------------------------------ PCI
def pci_read(bus, dev, fn, off, size=4):
    return edk2.readpci(bus, dev, fn, off, size)


def pci_scan():
    found = []
    for dev in range(32):
        for fn in range(8):
            v = pci_read(0, dev, fn, 0, 4)
            if v in (0xFFFFFFFF, 0):
                if fn == 0:
                    break
                continue
            cls = pci_read(0, dev, fn, 8, 4) >> 8
            found.append((0, dev, fn, v & 0xFFFF, v >> 16, cls))
            if fn == 0 and not (pci_read(0, dev, 0, 0x0C, 4) >> 16) & 0x80:
                break   # no multifunción
    return found


# ------------------------------------------------------------------ RAM física
class PhysRAM(object):
    """RAM física real reservada al firmware. Escrituras por palabras de 32 bits."""

    def __init__(self, size):
        if size % 4096:
            raise ValueError("RAM debe ser múltiplo de 4096")
        va = edk2.allocphysmem(size + 4096, 0xFFFFFFFF)
        va = va[0] if isinstance(va, tuple) else va
        if not va:
            raise MachineCheck("el firmware no pudo reservar %d bytes de RAM" % size)
        self.base = (va + 4095) & ~4095
        self.size = size

    def _check(self, a, n):
        if a < 0 or n < 0 or a + n > self.size:
            raise MachineCheck("acceso físico fuera de rango: %#x+%d" % (a, n))

    def read(self, a, n):
        self._check(a, n)
        if n == 0:
            return b""
        return edk2.readmem(self.base + a, 0, n)

    def read_u32(self, a):
        self._check(a, 4)
        return edk2.readmem_dword(self.base + a, 0) & 0xFFFFFFFF

    def write_u32(self, a, v):
        self._check(a, 4)
        edk2.writemem_dword(self.base + a, 0, v & 0xFFFFFFFF)

    def write(self, a, data):
        n = len(data)
        self._check(a, n)
        if n == 0:
            return
        data = bytes(data)
        start = a & ~3
        end = (a + n + 3) & ~3
        if start != a or end != a + n:
            cur = bytearray(edk2.readmem(self.base + start, 0, end - start))
            cur[a - start:a - start + n] = data
            data = bytes(cur)
        base = self.base + start
        wr = edk2.writemem_dword
        for i in range(0, len(data), 4):
            wr(base + i, 0, int.from_bytes(data[i:i + 4], "little"))

    def fill(self, a, n, v=0):
        if a % 4 == 0 and n % 4 == 0:
            self._check(a, n)
            word = v | (v << 8) | (v << 16) | (v << 24)
            wr = edk2.writemem_dword
            base = self.base + a
            for i in range(0, n, 4):
                wr(base + i, 0, word)
        else:
            self.write(a, bytes([v]) * n)

    def find_byte(self, v, s, e):
        self._check(s, e - s)
        chunk = 4096
        pos = s
        needle = bytes([v])
        while pos < e:
            n = min(chunk, e - pos)
            i = edk2.readmem(self.base + pos, 0, n).find(needle)
            if i >= 0:
                return pos + i
            pos += n
        return -1


# ------------------------------------------------------------------ disco
class FatFileDisk(object):
    """Disco de PyOS: fichero imagen en la partición FAT (E/S vía firmware)."""

    def __init__(self, path):
        self.path = path
        self._f = open(path, "r+b")
        self._f.seek(0, 2)
        size = self._f.tell()
        self.sectors = size // SECTOR
        self.reads = self.writes = 0

    def read(self, lba, n):
        if lba < 0 or n < 0 or lba + n > self.sectors:
            raise MachineCheck("lectura fuera de rango lba=%d" % lba)
        self._f.seek(lba * SECTOR)
        self.reads += n
        return self._f.read(n * SECTOR)

    def write(self, lba, data):
        n = len(data) // SECTOR
        if len(data) % SECTOR or lba < 0 or lba + n > self.sectors:
            raise MachineCheck("escritura de disco inválida lba=%d" % lba)
        self._f.seek(lba * SECTOR)
        self._f.write(data)
        self.writes += n

    def flush(self):
        self._f.flush()

    def close(self):
        if not self._f.closed:
            self._f.flush()
            self._f.close()


# ------------------------------------------------------------------ dispositivos
class PS2Keyboard(object):
    """Controlador i8042: entrega scancodes crudos (set 1) del teclado."""

    def __init__(self):
        status = edk2.readio(0x64, 1)
        self.present = status != 0xFF
        while self.present and edk2.readio(0x64, 1) & 1:
            edk2.readio(0x60, 1)

    def read_scancode(self):
        st = edk2.readio(0x64, 1)
        if st & 1 and not st & 0x20:     # dato disponible y no es del ratón
            return edk2.readio(0x60, 1)
        if st & 1:
            edk2.readio(0x60, 1)          # descarta bytes del ratón PS/2
        return None


class UART16550(object):
    def __init__(self, base=0x3F8):
        self.base = base
        edk2.writeio(base + 7, 1, 0x5A)
        self.present = edk2.readio(base + 7, 1) == 0x5A
        if self.present:
            edk2.writeio(base + 1, 1, 0x00)   # sin interrupciones (las sondeamos)
            edk2.writeio(base + 3, 1, 0x80)   # DLAB
            edk2.writeio(base + 0, 1, 0x01)   # 115200 baudios
            edk2.writeio(base + 1, 1, 0x00)
            edk2.writeio(base + 3, 1, 0x03)   # 8N1
            edk2.writeio(base + 2, 1, 0xC7)   # FIFO
            edk2.writeio(base + 4, 1, 0x0B)

    def has_data(self):
        return bool(edk2.readio(self.base + 5, 1) & 1)

    def read_byte(self):
        if edk2.readio(self.base + 5, 1) & 1:
            return edk2.readio(self.base, 1)
        return None

    def write(self, data):
        b = self.base
        for c in data:
            spins = 0
            while not edk2.readio(b + 5, 1) & 0x20 and spins < 10000:
                spins += 1
            edk2.writeio(b, 1, c)


def _raw_write(data):
    sys.stdout.flush()                       # por si quedó algo de print() del arranque
    view = memoryview(data)
    while len(view):
        try:
            n = os.write(1, view)
        except OSError:
            return
        if n <= 0:
            return
        view = view[n:]


class FirmwareConsole(object):
    """Pantalla: ConOut del firmware (texto sobre GOP). Refleja la salida en la UART.

    ConOut no entiende ANSI: las secuencias se interpretan en hal/ansi.py y el
    cursor se coloca con lseek() sobre stdout, que edk2-libc traduce a
    SimpleTextOutput.SetCursorPosition (offset = fila << 32 | columna).
    """
    ansi = True

    def __init__(self, uart):
        from .ansi import AnsiParser
        self.uart = uart
        self.out = []
        self._size = None
        self.parser = AnsiParser(self)

    suspended = False                       # LOOK tiene la pantalla: solo UART

    def write(self, data):
        if self.uart is not None and self.uart.present:
            self.uart.write(data)           # los terminales serie sí entienden ANSI
        if self.suspended:
            return
        try:
            self.parser.feed(data)
        except Exception:                   # un fallo de pantalla no debe tumbar la syscall
            import traceback
            self.out = []
            self.parser.pending = b""
            self.errors = getattr(self, "errors", 0) + 1
            if self.uart is not None and self.uart.present and self.errors <= 3:
                self.uart.write(("\r\n[consola] " + traceback.format_exc()).replace("\n", "\r\n").encode())

    # --- operaciones que pide el intérprete ANSI
    def text(self, s):
        self.out.append(s.replace("\r\n", "\n"))

    def flush(self):
        # Directo al descriptor 1 en UTF-8: edk2-libc convierte con mbrtowc (UTF-8) a
        # CHAR16 para ConOut. sys.stdout no sirve: su codificación no cubre los
        # caracteres de dibujo (█ ═ ║ ▲...) y fallaría.
        if self.out:
            data = "".join(self.out).encode("utf-8")
            self.out = []
            _raw_write(data)

    def _rawtext(self, s):
        _raw_write(s.encode("utf-8"))

    def _seek(self, r, c):
        self.flush()
        os.lseek(1, (r << 32) | c, 0)

    def _pos(self):
        self.flush()
        off = os.lseek(1, 0, 1)
        return off >> 32, off & 0xFFFFFFFF

    def goto(self, r, c):
        cols, rows = self.size()
        try:
            self._seek(min(max(r, 0), rows - 1), min(max(c, 0), cols - 1))
        except OSError:
            pass

    def move(self, dr, dc):
        try:
            r, c = self._pos()
        except OSError:
            return
        self.goto(r + dr, c + dc)

    def clear(self):
        """Pantalla en blanco sin pasar por el Shell: espacios fila a fila."""
        cols, rows = self.size()
        try:
            for r in range(rows):
                self._seek(r, 0)
                self._rawtext(" " * (cols - 1 if r == rows - 1 else cols))
            self._seek(0, 0)
        except OSError:
            _shell("cls")

    def erase_eol(self):
        cols, rows = self.size()
        try:
            r, c = self._pos()
            n = cols - c - (1 if r == rows - 1 else 0)
            if n > 0:
                self._rawtext(" " * n)
            self._seek(r, c)
        except OSError:
            pass

    def sgr(self, codes):
        pass                                # sin acceso a SetAttribute desde Python: monocromo

    def cursor(self, visible):
        pass

    def size(self):
        """Columnas y filas reales del modo de texto: se sondea qué posiciones acepta
        SetCursorPosition (falla fuera de la pantalla)."""
        if self._size is None:
            def ok(r, c):
                try:
                    os.lseek(1, (r << 32) | c, 0)
                    return True
                except OSError:
                    return False

            def limit(test, hi):
                lo = 1                       # lo siempre válido, hi inválido
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if test(mid):
                        lo = mid
                    else:
                        hi = mid
                return lo + 1
            try:
                saved = self._pos()
                cols = limit(lambda c: ok(0, c), 512)
                rows = limit(lambda r: ok(r, 0), 256)
                os.lseek(1, (saved[0] << 32) | saved[1], 0)
                self._size = (cols, rows) if cols >= 40 and rows >= 20 else (80, 25)
            except OSError:
                self._size = (80, 25)
        return self._size


class ACPITimer(object):
    def __init__(self, port):
        self.port = port
        self.last = edk2.readio(port, 4) & 0xFFFFFF
        self.ticks = 0

    def seconds(self):
        now = edk2.readio(self.port, 4) & 0xFFFFFF
        self.ticks += (now - self.last) & 0xFFFFFF
        self.last = now
        return self.ticks / float(PM_HZ)


def _find_pm_base(pci):
    for (_b, dev, fn, ven, did, _c) in pci:
        key = (did << 16) | ven
        if key in KNOWN_ACPI:
            reg = KNOWN_ACPI[key][1]
            base = pci_read(0, dev, fn, reg, 4) & 0xFFC0
            if base:
                return base, KNOWN_ACPI[key][0]
    for base in (0x4000, 0x600, 0xB000, 0x1800):   # VirtualBox, QEMU, OVMF...
        a = edk2.readio(base + 8, 4) & 0xFFFFFF
        for _ in range(2000):
            pass
        b = edk2.readio(base + 8, 4) & 0xFFFFFF
        if a != b and a not in (0xFFFFFF, 0):
            return base, "sondeo de puerto"
    return None, None


def _shell(cmd, out_file=None):
    if out_file:
        cmd = "%s > %s" % (cmd, out_file)
    return edk2.system(cmd)


def _read_shell_output(path):
    with open(path, "rb") as f:
        b = f.read()
    return b.decode("utf-16-le", "replace") if b[:2] == b"\xff\xfe" else b.decode("latin-1")


def _handles(devtree_text, needles):
    out = []
    for line in devtree_text.splitlines():
        if any(n in line for n in needles) and "Ctrl[" in line:
            out.append(line.split("Ctrl[")[1].split("]")[0])
    return out


class Machine(object):
    kind = "uefi"

    def __init__(self, ram_size, disk_path, scratch_dir="fs0:\\pyos", log=print):
        self.log = log
        self.own_volume = scratch_dir.split("\\")[0].lower()
        self.pci = pci_scan()
        pm_base, how = _find_pm_base(self.pci)
        if pm_base is None:
            raise MachineCheck("no se encontró el temporizador ACPI PM")
        self.pm_base = pm_base
        self.timer = ACPITimer(pm_base + 8)
        self.timer_how = how
        self._clear_power_button()
        self.scratch_dir = scratch_dir
        self._take_devices()
        self.ram = PhysRAM(ram_size)
        self.disk = FatFileDisk(disk_path)
        self.uart = UART16550()
        from .uefi_gfx import I8042
        self.kbd = I8042()                     # teclado + ratón PS/2 (puerto AUX)
        self.mouse = self.kbd
        self.console = FirmwareConsole(self.uart)
        self._fb = None
        self.nic = None
        self.nic_error = ""
        try:
            from .uefi_net import find, E1000
            loc = find(self.pci)
            if loc is not None:
                self.nic = E1000(loc[0], loc[1], loc[2], loc[3], self.timer.seconds)
            else:
                self.nic_error = "no hay tarjeta de red e1000"
        except Exception as e:                  # la red es opcional: PyOS arranca sin ella
            self.nic = None
            self.nic_error = "e1000: %s" % e
        self._wall0 = time.time()
        self._clk0 = self.timer.seconds()
        self._entropy = 0
        self._spin_per_ms = self._calibrate_spin()

    def _take_devices(self):
        """El firmware suelta el teclado y el puerto serie: PyOS los maneja directamente."""
        tree = self.scratch_dir + "\\devtree.txt"
        _shell("devtree", tree)
        text = _read_shell_output(tree)
        self.released = []
        nic_paths = []
        if getattr(self, "pci", None):
            from .uefi_net import find
            loc = find(self.pci)
            if loc is not None:
                nic_paths.append(("pci(0x%x,0x%x)" % (loc[1], loc[2])))
        nic_handles = [l.split("Ctrl[")[1].split("]")[0] for l in text.splitlines()
                       if "Ctrl[" in l and any(l.rstrip().lower().endswith(p) for p in nic_paths)]
        for h in (_handles(text, ("PS/2 Keyboard Device", "PS/2 Mouse")) +
                  _handles(text, ("Serial(0x0)",))[:1] + nic_handles[:1]):
            if _shell("disconnect %s" % h, self.scratch_dir + "\\disc.txt") == 0:
                self.released.append(h)
        _shell("cls")

    # --- gráficos
    def framebuffer(self):
        """Framebuffer del modo que dejó el firmware (lanza GfxError si no se puede usar)."""
        if self._fb is None:
            from .uefi_gfx import detect, LinearFramebuffer
            self._fb = LinearFramebuffer(*detect(self.pci))
        return self._fb

    def text_console_restore(self):
        """Tras LOOK: pantalla negra y la consola de texto del firmware se redibuja."""
        self.console.suspended = False
        self.console.clear()

    # --- tiempo
    def clock(self):
        return self.timer.seconds()

    def wall(self):
        return self._wall0 + (self.clock() - self._clk0)

    # --- ACPI
    def _clear_power_button(self):
        edk2.writeio(self.pm_base, 2, 0x0100)                    # PM1_STS: limpia PWRBTN_STS
        en = edk2.readio(self.pm_base + 2, 2)
        edk2.writeio(self.pm_base + 2, 2, en | 0x0100)           # PM1_EN: PWRBTN_EN

    def power_button_pressed(self):
        if edk2.readio(self.pm_base, 2) & 0x0100:
            self._clear_power_button()
            return True
        return False

    # --- otros sistemas arrancables (selector)
    def boot_entries(self):
        import os
        from ..boot.selector import detect_linux
        vols = ["fs%d:" % i for i in range(16) if "fs%d:" % i != self.own_volume]
        return detect_linux(os.listdir, vols)

    def chainload(self, loader):
        """Devuelve el teclado/serie al firmware y cede la máquina al cargador EFI."""
        self.disk.flush()
        _shell("connect -r")
        _shell("cls")
        rc = _shell(loader)
        # Si el cargador vuelve (el usuario salió de GRUB, fallo...), PyOS recupera
        # el teclado y la UART antes de volver a dibujar el selector.
        self._take_devices()
        return rc

    def power_off(self):
        self.disk.flush()
        _shell("reset -s")

    def reset(self):
        self.disk.flush()
        _shell("reset")

    def _calibrate_spin(self):
        """Cuántas vueltas de un bucle de cálculo puro (sin E/S) caben en 1 ms."""
        n, t0 = 2000, self.timer.seconds()
        while True:
            for _ in range(n):
                pass
            dt = self.timer.seconds() - t0
            if dt >= 0.005:
                return max(100, int(n / (dt * 1000.0)))
            n *= 2

    def idle(self):
        """Sin HLT posible desde Python: se espera ~2 ms SIN tocar puertos de E/S.

        Cada acceso a un puerto es una salida de la VM al hipervisor (muy cara con
        Hyper-V/NEM); un bucle de cálculo puro no provoca ninguna.
        """
        for _ in range(self._spin_per_ms * 2):
            pass

    def random_bytes(self, n):
        import hashlib
        out = b""
        while len(out) < n:
            self._entropy += 1
            seed = ("%d:%d:%d" % (edk2.readio(self.pm_base + 8, 4), self._entropy, self.timer.ticks)).encode()
            out += hashlib.sha256(seed).digest()
        return out[:n]

    def info(self):
        try:
            regs = [edk2.cpuid(0x80000002 + i, 0) for i in range(3)]
            brand = b"".join(b"".join(int(r).to_bytes(4, "little") for r in t) for t in regs)
            cpu = brand.decode("ascii", "replace").strip("\x00 ")
        except Exception:
            cpu = "?"
        return {"platform": "hardware real sobre UEFI (sin sistema operativo)",
                "cpu": cpu,
                "timer": "ACPI PM timer en puerto %#x (%s)" % (self.pm_base + 8, self.timer_how),
                "pci": ["%02x:%02x.%d %04x:%04x clase %06x" % p for p in self.pci],
                "firmware": "UEFI (drivers liberados: %s)" % (", ".join(self.released) or "ninguno"),
                "uart": "COM1 0x3F8" if self.uart.present else "sin UART",
                "kbd": "i8042 PS/2" if self.kbd.present else "sin PS/2"}

    def shutdown(self):
        self.disk.close()
