"""Selector de arranque de PyOS.

Se ejecuta en la etapa de firmware, antes del kernel. Ofrece:
  1. PyOS LOOK   (entorno gráfico; si no está instalado, init cae a Term)
  2. PyOS Term   (terminal de administración)
  3+ Linux       (una entrada por cada cargador de distribución encontrado)

Espera indefinidamente: no arranca nada hasta que el usuario elige.
Teclas: flechas arriba/abajo + Intro, o el número de la opción.
"""

KNOWN_DISTROS = (
    ("ubuntu", "Ubuntu"), ("kali", "Kali Linux"), ("arch", "Arch Linux"),
    ("debian", "Debian"), ("fedora", "Fedora"), ("opensuse", "openSUSE"),
    ("alpine", "Alpine Linux"), ("manjaro", "Manjaro"), ("mint", "Linux Mint"),
    ("pop", "Pop!_OS"), ("gentoo", "Gentoo"), ("systemd", "Linux (systemd-boot)"),
    ("grub", "Linux (GRUB)"),
)
LOADERS = ("shimx64.efi", "grubx64.efi", "systemd-bootx64.efi")
SKIP_DIRS = ("boot", "tools", "stdlib", "microsoft", "pyos")


class Entry(object):
    def __init__(self, title, kind, mode=None, loader=None, note=""):
        self.title, self.kind, self.mode, self.loader, self.note = title, kind, mode, loader, note

    def __repr__(self):
        return "<Entry %s %s %s>" % (self.title, self.kind, self.loader or self.mode)


def pyos_entries():
    return [Entry("PyOS LOOK", "pyos", "look", note="entorno gráfico (opcional)"),
            Entry("PyOS Term", "pyos", "term", note="terminal de administración")]


def distro_name(dirname):
    low = dirname.lower()
    for key, name in KNOWN_DISTROS:
        if key in low:
            return name
    return "Linux (%s)" % dirname


def detect_linux(listdir, volumes):
    """Busca cargadores EFI de distribuciones Linux en las particiones dadas.

    listdir(path) -> lista de nombres (lanza OSError si no existe)
    volumes: prefijos de volumen a explorar, p. ej. ["fs1:", "fs2:"]
    """
    found = []
    for vol in volumes:
        try:
            efi = listdir(vol + "\\EFI")
        except OSError:
            continue
        for d in sorted(efi):
            if d.lower() in SKIP_DIRS:
                continue
            try:
                files = dict((f.lower(), f) for f in listdir(vol + "\\EFI\\" + d))
            except OSError:
                continue
            for loader in LOADERS:
                if loader in files:
                    path = "%s\\EFI\\%s\\%s" % (vol, d, files[loader])
                    found.append(Entry(distro_name(d), "linux", loader=path,
                                       note="%s en %s" % (files[loader], vol)))
                    break
    return found


def render(entries, sel, info=""):
    lines = ["", "  PyOS — Your machine. Your system. Your rules.", "",
             "  Elige cómo arrancar (flechas + Intro, o el número):", ""]
    for i, e in enumerate(entries):
        mark = ">" if i == sel else " "
        lines.append("   %s %d. %-24s %s" % (mark, i + 1, e.title, e.note))
    lines.append("")
    if not any(e.kind == "linux" for e in entries):
        lines.append("  (no se ha encontrado ninguna distribución Linux instalada)")
    if info:
        lines.append("  " + info)
    lines.append("  Esperando tu elección: no se arrancará nada automáticamente.")
    return "\n".join(lines) + "\n"


class KeyDecoder(object):
    """Convierte scancodes PS/2 y bytes serie en acciones del menú."""

    def __init__(self):
        self.e0 = False
        self.esc = b""

    def scancode(self, sc):
        if sc == 0xE0:
            self.e0 = True
            return None
        e0, self.e0 = self.e0, False
        if sc & 0x80:
            return None
        if e0 and sc == 0x48:
            return "up"
        if e0 and sc == 0x50:
            return "down"
        if sc in (0x1C,) or (e0 and sc == 0x1C):
            return "enter"
        if 0x02 <= sc <= 0x0A:
            return sc - 0x01           # tecla '1'..'9'
        return None

    def byte(self, b):
        if self.esc or b == 0x1B:
            self.esc += bytes([b])
            if self.esc in (b"\x1b[A",):
                self.esc = b""
                return "up"
            if self.esc in (b"\x1b[B",):
                self.esc = b""
                return "down"
            if len(self.esc) >= 3:
                self.esc = b""
            return None
        if b in (0x0D, 0x0A):
            return "enter"
        if 0x31 <= b <= 0x39:
            return b - 0x30
        return None


def choose(machine, entries, info=""):
    """Bucle del menú. Devuelve la entrada elegida (espera indefinida)."""
    say = machine.console.write
    sel = 1 if len(entries) > 1 else 0
    dec = KeyDecoder()

    def draw():
        clear = getattr(machine.console, "clear", None)
        if clear is not None:
            clear()
        say(render(entries, sel, info).replace("\n", "\r\n").encode("utf-8"))

    draw()
    kbd = getattr(machine, "kbd", None)
    uart = getattr(machine, "uart", None)
    while True:
        actions = []
        if kbd is not None and kbd.present:
            sc = kbd.read_scancode()
            while sc is not None:
                actions.append(dec.scancode(sc))
                sc = kbd.read_scancode()
        if uart is not None and uart.present:
            b = uart.read_byte()
            while b is not None:
                actions.append(dec.byte(b))
                b = uart.read_byte()
        if not actions:
            machine.idle()
            continue
        for a in actions:
            if a is None:
                continue
            if a == "up":
                sel = (sel - 1) % len(entries)
                draw()
            elif a == "down":
                sel = (sel + 1) % len(entries)
                draw()
            elif a == "enter":
                return entries[sel]
            elif isinstance(a, int) and 1 <= a <= len(entries):
                return entries[a - 1]
