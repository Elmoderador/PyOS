"""Selector de arranque: detección de distribuciones, teclas y elección (sin red ni QEMU)."""
from pyos.boot import firmware, selector
from pyos.hal.emulated import Raw, ScriptConsole


def fake_fs(tree):
    def listdir(path):
        node = tree
        for part in path.replace(":", ":\\").split("\\"):
            if not part:
                continue
            if not isinstance(node, dict) or part not in node:
                raise OSError(2, path)
            node = node[part]
        return list(node)
    return listdir


TREE = {
    "fs0:": {"EFI": {"BOOT": {"BOOTX64.EFI": 1}, "pyos": {"x": 1}}},
    "fs1:": {"EFI": {"ubuntu": {"shimx64.efi": 1, "grubx64.efi": 1}, "BOOT": {"BOOTX64.EFI": 1}}},
    "fs2:": {"EFI": {"arch": {"GRUBX64.EFI": 1}, "systemd": {"systemd-bootx64.efi": 1},
                     "Microsoft": {"bootmgfw.efi": 1}}},
    "fs3:": {"datos": {}},
}


def test_detecta_distros_y_prefiere_shim():
    found = selector.detect_linux(fake_fs(TREE), ["fs0:", "fs1:", "fs2:", "fs3:", "fs9:"])
    loaders = [e.loader for e in found]
    assert "fs1:\\EFI\\ubuntu\\shimx64.efi" in loaders          # shim antes que grub (Secure Boot)
    assert "fs1:\\EFI\\ubuntu\\grubx64.efi" not in loaders
    assert "fs2:\\EFI\\arch\\GRUBX64.EFI" in loaders             # respeta mayúsculas reales
    assert not any("Microsoft" in l or "BOOT" in l for l in loaders)
    names = [e.title for e in found]
    assert "Ubuntu" in names and "Arch Linux" in names
    assert all(e.kind == "linux" for e in found)


def test_sin_distros():
    assert selector.detect_linux(fake_fs({"fs0:": {}}), ["fs0:", "fs1:"]) == []
    txt = selector.render(selector.pyos_entries(), 1)
    assert "no se ha encontrado ninguna distribución" in txt and "> 2. PyOS Term" in txt


def test_decodificador_de_teclas():
    d = selector.KeyDecoder()
    assert [d.scancode(x) for x in (0xE0, 0x48)] == [None, "up"]
    assert [d.scancode(x) for x in (0xE0, 0x50)] == [None, "down"]
    assert d.scancode(0x1C) == "enter" and d.scancode(0x03) == 2 and d.scancode(0x83) is None
    assert [d.byte(b) for b in b"\x1b[A"] == [None, None, "up"]
    assert [d.byte(b) for b in b"\x1b[B"] == [None, None, "down"]
    assert d.byte(ord("1")) == 1 and d.byte(13) == "enter" and d.byte(ord("x")) is None


class FakeMachine(object):
    def __init__(self, keys):
        self.console = ScriptConsole([Raw(keys)], eof_at_end=None, timeout=5)
        self.uart = self.console
        self.kbd = None
        self.idles = 0

    def idle(self):
        self.idles += 1
        if self.idles > 200000:
            raise AssertionError("el selector no reaccionó a las teclas")


def test_eleccion_por_numero_y_flechas():
    entries = selector.pyos_entries() + [selector.Entry("Ubuntu", "linux", loader="fs1:\\x.efi")]
    assert selector.choose(FakeMachine(b"3"), entries).title == "Ubuntu"
    assert selector.choose(FakeMachine(b"\r"), entries).mode == "term"          # por defecto: Term
    assert selector.choose(FakeMachine(b"\x1b[A\r"), entries).mode == "look"
    assert selector.choose(FakeMachine(b"\x1b[B\r"), entries).kind == "linux"
    assert selector.choose(FakeMachine(b"9\r"), entries).mode == "term"         # número fuera de rango


def test_firmware_vuelve_al_selector_si_falla_el_chainload(tmp_path):
    from pyos.hal import emulated
    from pyos.tools import mkimage
    img = str(tmp_path / "p.img")
    mkimage.build(img, size_mb=8)
    con = ScriptConsole([Raw(b"3", 0.05), Raw(b"2", 0.3), "halt"], timeout=20)
    m = emulated.Machine(16 << 20, img, con)
    m.boot_entries = lambda: [selector.Entry("Kali Linux", "linux", loader="fs1:\\EFI\\kali\\grubx64.efi")]
    calls = []
    m.chainload = lambda loader: calls.append(loader) or -1
    try:
        rc = firmware.power_on(m, None)
    finally:
        m.shutdown()
    out = con.transcript
    assert calls == ["fs1:\\EFI\\kali\\grubx64.efi"]
    assert "No se pudo arrancar Kali Linux" in out and "Modo de arranque: PyOS Term" in out
    assert rc == firmware.EXIT_HALT
