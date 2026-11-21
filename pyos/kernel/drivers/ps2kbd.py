"""Driver de teclado PS/2 (scancode set 1) con distribuciones 'es' y 'us'.

Recibe scancodes crudos del controlador i8042 y produce bytes UTF-8 hacia la
TTY. Soporta Mayús, Bloq Mayús, Ctrl, Alt, AltGr, teclas muertas (´ ` ¨ ^) y
la combinación Ctrl+Alt+Supr.
"""
from .devices import CharDevice

# (normal, mayús, altgr) por scancode; None = sin carácter
_COMMON = {
    0x01: ("\x1b", "\x1b", None), 0x0E: ("\x7f", "\x7f", None), 0x0F: ("\t", "\t", None),
    0x1C: ("\r", "\r", None), 0x39: (" ", " ", None),
}
_LETTERS = {0x10: "q", 0x11: "w", 0x12: "e", 0x13: "r", 0x14: "t", 0x15: "y", 0x16: "u",
            0x17: "i", 0x18: "o", 0x19: "p", 0x1E: "a", 0x1F: "s", 0x20: "d", 0x21: "f",
            0x22: "g", 0x23: "h", 0x24: "j", 0x25: "k", 0x26: "l", 0x2C: "z", 0x2D: "x",
            0x2E: "c", 0x2F: "v", 0x30: "b", 0x31: "n", 0x32: "m"}

LAYOUTS = {
    "us": {
        0x02: ("1", "!", None), 0x03: ("2", "@", None), 0x04: ("3", "#", None),
        0x05: ("4", "$", None), 0x06: ("5", "%", None), 0x07: ("6", "^", None),
        0x08: ("7", "&", None), 0x09: ("8", "*", None), 0x0A: ("9", "(", None),
        0x0B: ("0", ")", None), 0x0C: ("-", "_", None), 0x0D: ("=", "+", None),
        0x1A: ("[", "{", None), 0x1B: ("]", "}", None), 0x27: (";", ":", None),
        0x28: ("'", '"', None), 0x29: ("`", "~", None), 0x2B: ("\\", "|", None),
        0x33: (",", "<", None), 0x34: (".", ">", None), 0x35: ("/", "?", None),
        0x56: ("\\", "|", None),
    },
    "es": {
        0x02: ("1", "!", "|"), 0x03: ("2", '"', "@"), 0x04: ("3", "·", "#"),
        0x05: ("4", "$", "~"), 0x06: ("5", "%", "€"), 0x07: ("6", "&", "¬"),
        0x08: ("7", "/", None), 0x09: ("8", "(", None), 0x0A: ("9", ")", None),
        0x0B: ("0", "=", None), 0x0C: ("'", "?", "\\"), 0x0D: ("¡", "¿", None),
        0x1A: ("DEAD`", "DEAD^", "["), 0x1B: ("+", "*", "]"), 0x27: ("ñ", "Ñ", None),
        0x28: ("DEAD´", "DEAD¨", "{"), 0x29: ("º", "ª", "\\"), 0x2B: ("ç", "Ç", "}"),
        0x33: (",", ";", None), 0x34: (".", ":", None), 0x35: ("-", "_", None),
        0x56: ("<", ">", None),
    },
}
_DEAD = {
    "´": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"},
    "`": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù", "A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"},
    "¨": {"a": "ä", "e": "ë", "i": "ï", "o": "ö", "u": "ü", "A": "Ä", "E": "Ë", "I": "Ï", "O": "Ö", "U": "Ü"},
    "^": {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û", "A": "Â", "E": "Ê", "I": "Î", "O": "Ô", "U": "Û"},
}
# Teclas extendidas (prefijo E0) -> secuencias VT100
_E0 = {0x48: "\x1b[A", 0x50: "\x1b[B", 0x4D: "\x1b[C", 0x4B: "\x1b[D", 0x1C: "\r",
       0x35: "/", 0x47: "\x1b[H", 0x4F: "\x1b[F", 0x53: "\x1b[3~",
       0x49: "\x1b[5~", 0x51: "\x1b[6~", 0x52: "\x1b[2~",
       0x5B: "\x1b[29~", 0x5C: "\x1b[29~"}          # tecla Windows/Super -> menú de LOOK
# Teclas de función (secuencias xterm)
_FKEYS = {0x3B: "\x1bOP", 0x3C: "\x1bOQ", 0x3D: "\x1bOR", 0x3E: "\x1bOS", 0x3F: "\x1b[15~",
          0x40: "\x1b[17~", 0x41: "\x1b[18~", 0x42: "\x1b[19~", 0x43: "\x1b[20~",
          0x44: "\x1b[21~", 0x57: "\x1b[23~", 0x58: "\x1b[24~"}


class PS2Keyboard(CharDevice):
    name, major, minor = "kbd", 13, 0
    description = "teclado PS/2 (i8042, scancode set 1)"

    def __init__(self, hw, sink, on_ctrl_alt_del, layout="es"):
        self.hw = hw
        self.sink = sink                  # función(bytes) -> TTY
        self.on_cad = on_ctrl_alt_del
        self.layout_name = layout if layout in LAYOUTS else "es"
        self.table = dict(_COMMON)
        self.table.update(LAYOUTS[self.layout_name])
        self.shift = self.ctrl = self.alt = self.altgr = self.caps = False
        self.e0 = False
        self.dead = None
        self.scancodes = 0
        self.irq = 1

    def set_layout(self, name):
        if name not in LAYOUTS:
            raise ValueError(name)
        self.layout_name = name
        self.table = dict(_COMMON)
        self.table.update(LAYOUTS[name])
        self.dead = None

    def open(self, flags):
        from ..errors import KError, EPERM
        raise KError(EPERM, "el teclado se lee a través de /dev/tty")

    def interrupt(self):
        while True:
            sc = self.hw.read_scancode()
            if sc is None:
                return
            self.scancodes += 1
            self._scancode(sc)

    def _scancode(self, sc):
        if sc == 0xE0:
            self.e0 = True
            return
        release = bool(sc & 0x80)
        code = sc & 0x7F
        e0, self.e0 = self.e0, False
        if code in (0x2A, 0x36):
            self.shift = not release
            return
        if code == 0x1D:
            self.ctrl = not release
            return
        if code == 0x38:
            if e0:
                self.altgr = not release
            else:
                self.alt = not release
            return
        if release:
            return
        if code == 0x3A:
            self.caps = not self.caps
            return
        if e0:
            if code == 0x53 and self.ctrl and self.alt:
                self.on_cad()
                return
            seq = _E0.get(code)
            if seq:
                self.sink(seq.encode())
            return
        if code == 0x53 and self.ctrl and self.alt:   # Supr del bloque numérico
            self.on_cad()
            return
        if code in _FKEYS:
            self.sink(_FKEYS[code].encode())
            return
        if self.alt and not self.altgr and not self.ctrl:
            # Alt+tecla -> ESC + tecla (convenio xterm "meta"); Alt+Tab -> ESC TAB
            if code == 0x0F:
                self.sink(b"\x1b\t")
                return
            if code in _LETTERS:
                self.sink(b"\x1b" + _LETTERS[code].encode())
                return
        if code in _LETTERS:
            ch = _LETTERS[code]
            if self.ctrl:
                self.sink(bytes([ord(ch) - 96]))
                return
            if self.shift != self.caps:
                ch = ch.upper()
            self._emit(ch)
            return
        entry = self.table.get(code)
        if entry is None:
            return
        normal, shifted, altgr = entry
        ch = altgr if (self.altgr or (self.ctrl and self.alt)) and altgr else (shifted if self.shift else normal)
        if ch is None:
            return
        if self.ctrl and ch in ("]", "+") :
            self.sink(b"\x1d")
            return
        self._emit(ch)

    def _emit(self, ch):
        if ch.startswith("DEAD"):
            mark = ch[4:]
            if self.dead is not None:          # dos muertas seguidas: escribe la marca
                self.sink(self.dead.encode("utf-8"))
                self.dead = None
                return
            self.dead = mark
            return
        if self.dead is not None:
            combo = _DEAD.get(self.dead, {}).get(ch)
            out = combo if combo else (self.dead + ch if ch != " " else self.dead)
            self.dead = None
            self.sink(out.encode("utf-8"))
            return
        self.sink(ch.encode("utf-8"))
