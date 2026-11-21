"""Driver de red Intel 8254x (e1000) en Python para la HAL UEFI.

Es la tarjeta que emulan por defecto QEMU (-nic ... model=e1000) y VirtualBox
("Intel PRO/1000 MT Desktop", 82540EM). Antes de tocarla, PyOS desconecta del
controlador los drivers del firmware (iPXE/SNP/MNP), que si no seguirían leyendo
los anillos de recepción por su cuenta.

* Registros por MMIO (BAR0) con readmem_dword/writemem_dword.
* Anillos de descriptores y búferes en RAM física reservada al firmware
  (allocphysmem; en UEFI x86 la dirección virtual es la física) para DMA.
* Bus master activado en el registro de comando PCI.
* Sin interrupciones: el kernel sondea los descriptores (como el resto de PyOS).
"""
import struct

import edk2

IDS = {(0x8086, 0x100E): "Intel 82540EM (e1000)", (0x8086, 0x100F): "Intel 82545EM (e1000)",
       (0x8086, 0x1004): "Intel 82543GC (e1000)", (0x8086, 0x100C): "Intel 82544GC (e1000)",
       (0x8086, 0x10D3): "Intel 82574L (e1000e, descriptores clásicos)"}

CTRL, STATUS, EERD, ICR, IMC = 0x0000, 0x0008, 0x0014, 0x00C0, 0x00D8
RCTL, TCTL, TIPG = 0x0100, 0x0400, 0x0410
RDBAL, RDBAH, RDLEN, RDH, RDT = 0x2800, 0x2804, 0x2808, 0x2810, 0x2818
TDBAL, TDBAH, TDLEN, TDH, TDT = 0x3800, 0x3804, 0x3808, 0x3810, 0x3818
MTA, RAL0, RAH0 = 0x5200, 0x5400, 0x5404
NRX, NTX, BUF = 32, 32, 2048


def find(pci_devices):
    for bus, dev, fn, ven, did, cls in pci_devices:
        if (ven, did) in IDS:
            return bus, dev, fn, IDS[(ven, did)]
    return None


def _alloc(n):
    va = edk2.allocphysmem(n + 4096, 0xFFFFFFFF)
    va = va[0] if isinstance(va, tuple) else va
    if not va:
        raise OSError("sin memoria física para DMA")
    return (va + 4095) & ~4095


class E1000(object):
    def __init__(self, bus, dev, fn, desc, clock):
        self.desc = desc
        self.loc = (bus, dev, fn)
        bar = edk2.readpci(bus, dev, fn, 0x10, 4)
        if bar & 1:
            raise OSError("BAR0 de E/S: no soportado")
        base = bar & 0xFFFFFFF0
        if (bar >> 1) & 3 == 2:
            base |= edk2.readpci(bus, dev, fn, 0x14, 4) << 32
        self.mmio = base
        cmd = edk2.readpci(bus, dev, fn, 0x04, 2)
        edk2.writepci(bus, dev, fn, 0x04, cmd | 0x06, 2)      # memoria + bus master
        # reinicio
        self.w(IMC, 0xFFFFFFFF)
        self.w(CTRL, self.r(CTRL) | (1 << 26))
        t0 = clock()
        while clock() - t0 < 0.05:
            pass
        while self.r(CTRL) & (1 << 26) and clock() - t0 < 1.0:
            pass
        self.w(IMC, 0xFFFFFFFF)
        self.r(ICR)
        ctrl = self.r(CTRL)
        ctrl |= (1 << 6) | (1 << 5)                   # SLU + ASDE
        ctrl &= ~((1 << 3) | (1 << 31) | (1 << 7))    # sin LRST/PHY_RST/ILOS
        self.w(CTRL, ctrl)
        self.mac = self._read_mac()
        for i in range(128):
            self.w(MTA + 4 * i, 0)
        # anillo de recepción
        self.rx_ring = _alloc(NRX * 16)
        self.rx_bufs = _alloc(NRX * BUF)
        for i in range(NRX):
            self._desc(self.rx_ring, i, self.rx_bufs + i * BUF)
        self.w(RDBAL, self.rx_ring & 0xFFFFFFFF)
        self.w(RDBAH, self.rx_ring >> 32)
        self.w(RDLEN, NRX * 16)
        self.w(RDH, 0)
        self.w(RDT, NRX - 1)
        self.rx_i = 0
        self.w(RCTL, (1 << 1) | (1 << 15) | (1 << 26))  # EN, BAM, SECRC, BSIZE=2048
        # anillo de transmisión
        self.tx_ring = _alloc(NTX * 16)
        self.tx_bufs = _alloc(NTX * BUF)
        for i in range(NTX):
            self._desc(self.tx_ring, i, self.tx_bufs + i * BUF)
            self.wm(self.tx_ring + i * 16 + 12, 1)      # DD=1: libre
        self.w(TDBAL, self.tx_ring & 0xFFFFFFFF)
        self.w(TDBAH, self.tx_ring >> 32)
        self.w(TDLEN, NTX * 16)
        self.w(TDH, 0)
        self.w(TDT, 0)
        self.tx_i = 0
        self.w(TCTL, (1 << 1) | (1 << 3) | (0x0F << 4) | (0x40 << 12))
        self.w(TIPG, 0x0060200A)
        self.tx_drop = 0

    # --- acceso a registros y memoria
    def r(self, off):
        a = self.mmio + off
        return edk2.readmem_dword(a & 0xFFFFFFFF, a >> 32)

    def w(self, off, v):
        a = self.mmio + off
        edk2.writemem_dword(a & 0xFFFFFFFF, a >> 32, v & 0xFFFFFFFF)

    @staticmethod
    def wm(addr, v):
        edk2.writemem_dword(addr & 0xFFFFFFFF, addr >> 32, v & 0xFFFFFFFF)

    @staticmethod
    def rm(addr, n):
        return edk2.readmem(addr & 0xFFFFFFFF, addr >> 32, n)

    def _desc(self, ring, i, buf):
        a = ring + i * 16
        self.wm(a, buf & 0xFFFFFFFF)
        self.wm(a + 4, buf >> 32)
        self.wm(a + 8, 0)
        self.wm(a + 12, 0)

    def _read_mac(self):
        lo, hi = self.r(RAL0), self.r(RAH0)
        if hi & 0x80000000 and (lo or hi & 0xFFFF):
            return struct.pack("<IH", lo, hi & 0xFFFF)
        words = []
        for i in range(3):
            self.w(EERD, (i << 8) | 1)
            for _ in range(100000):
                v = self.r(EERD)
                if v & 0x10:
                    words.append(v >> 16)
                    break
            else:
                raise OSError("no se pudo leer la EEPROM")
        mac = struct.pack("<HHH", *words)
        self.w(RAL0, struct.unpack("<I", mac[:4])[0])
        self.w(RAH0, struct.unpack("<H", mac[4:])[0] | 0x80000000)
        return mac

    # --- interfaz de NIC para la pila
    def link_up(self):
        return bool(self.r(STATUS) & 2)

    def send(self, frame):
        i = self.tx_i
        d = self.tx_ring + i * 16
        if not self.rm(d + 12, 1)[0] & 1:               # aún no se ha enviado lo anterior
            self.tx_drop += 1
            return False
        n = len(frame)
        if n > BUF:
            return False
        pad = frame + b"\x00" * (-n % 4)
        words = struct.unpack("<%dI" % (len(pad) // 4), pad)
        buf = self.tx_bufs + i * BUF
        lo, hi = buf & 0xFFFFFFFF, buf >> 32
        wr = edk2.writemem_dword
        for k, v in enumerate(words):
            wr(lo + 4 * k, hi, v)
        self.wm(d + 8, n | (0x0B << 24))               # EOP | IFCS | RS
        self.wm(d + 12, 0)
        self.tx_i = (i + 1) % NTX
        self.w(TDT, self.tx_i)
        return True

    def poll(self):
        out = []
        for _ in range(NRX):
            i = self.rx_i
            d = self.rx_ring + i * 16
            meta = self.rm(d + 8, 8)
            if not meta[4] & 1:                         # DD
                break
            length = meta[0] | (meta[1] << 8)
            if meta[4] & 2 and not meta[5] and 14 <= length <= BUF:   # EOP sin errores
                out.append(self.rm(self.rx_bufs + i * BUF, length))
            self.wm(d + 8, 0)
            self.wm(d + 12, 0)
            self.w(RDT, i)
            self.rx_i = (i + 1) % NRX
        return out

    def stop(self):
        self.w(RCTL, 0)
        self.w(TCTL, 0)
        self.w(IMC, 0xFFFFFFFF)
