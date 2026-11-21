"""Intérprete de secuencias ANSI/VT100 para pantallas que no las entienden.

La consola de texto del firmware UEFI imprime ESC como "^[": PyOS traduce aquí
las secuencias a operaciones de la pantalla (posicionar el cursor, borrar...).
Lo usan la consola del firmware y la pantalla virtual de los tests.

Soportado: CSI H/f (posición), A/B/C/D (movimiento), J (borrar pantalla),
K (borrar hasta fin de línea), m (atributos: se pasan a la pantalla si sabe
usarlos), ?25l/?25h (cursor), resto: se descarta sin imprimir basura.
"""
import codecs


class AnsiParser(object):
    MAX_SEQ = 32

    def __init__(self, screen):
        self.screen = screen          # text(str) goto(r,c) move(dr,dc) clear() erase_eol() sgr(list) cursor(bool)
        self.pending = b""
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")

    def feed(self, data):
        buf = self.pending + bytes(data)
        self.pending = b""
        i, n = 0, len(buf)
        while i < n:
            j = buf.find(b"\x1b", i)
            if j < 0:
                self._text(buf[i:])
                break
            if j > i:
                self._text(buf[i:j])
            if j + 1 >= n:
                self.pending = buf[j:]
                break
            if buf[j + 1] != 0x5B:          # ESC sin '[': se descarta el par
                i = j + 2
                continue
            k = j + 2
            while k < n and 0x30 <= buf[k] <= 0x3F:
                k += 1
            if k >= n:
                if n - j < self.MAX_SEQ:
                    self.pending = buf[j:]
                break
            self._csi(buf[j + 2:k].decode("ascii", "replace"), chr(buf[k]))
            i = k + 1
        self.screen.flush()

    def _text(self, b):
        s = self.dec.decode(b)
        if s:
            self.screen.text(s)

    @staticmethod
    def _nums(params, count, default):
        vals = []
        for p in params.split(";"):
            try:
                vals.append(int(p))
            except ValueError:
                vals.append(default)
        while len(vals) < count:
            vals.append(default)
        return vals

    def _csi(self, params, final):
        s = self.screen
        if params.startswith("?"):
            if params == "?25l" or (params == "?25" and final == "l"):
                s.cursor(False)
            elif params == "?25" and final == "h":
                s.cursor(True)
            return
        if final in "Hf":
            r, c = self._nums(params, 2, 1)
            s.goto(max(r, 1) - 1, max(c, 1) - 1)
        elif final in "ABCD":
            d = max(self._nums(params, 1, 1)[0], 1)
            dr, dc = {"A": (-d, 0), "B": (d, 0), "C": (0, d), "D": (0, -d)}[final]
            s.move(dr, dc)
        elif final == "J":
            if self._nums(params, 1, 0)[0] in (2, 3):
                s.clear()
        elif final == "K":
            if self._nums(params, 1, 0)[0] == 0:
                s.erase_eol()
        elif final == "m":
            s.sgr(self._nums(params, 1, 0))


class GridScreen(object):
    """Pantalla virtual en memoria (tests y depuración): rejilla de caracteres."""

    def __init__(self, cols=80, rows=25):
        self.cols, self.rows = cols, rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.r = self.c = 0
        self.parser = AnsiParser(self)

    def write(self, data):
        self.parser.feed(data)

    def text(self, s):
        for ch in s:
            if ch == "\n":
                self.r, self.c = min(self.r + 1, self.rows - 1), 0
            elif ch == "\r":
                self.c = 0
            elif ch == "\b":
                self.c = max(0, self.c - 1)
            elif ch >= " ":
                if self.c >= self.cols:
                    self.c = 0
                    self.r = min(self.r + 1, self.rows - 1)
                self.grid[self.r][self.c] = ch
                self.c += 1

    def goto(self, r, c):
        self.r, self.c = min(max(r, 0), self.rows - 1), min(max(c, 0), self.cols - 1)

    def move(self, dr, dc):
        self.goto(self.r + dr, self.c + dc)

    def clear(self):
        self.grid = [[" "] * self.cols for _ in range(self.rows)]
        self.r = self.c = 0

    def erase_eol(self):
        for c in range(self.c, self.cols):
            self.grid[self.r][c] = " "

    def sgr(self, codes):
        pass

    def cursor(self, visible):
        pass

    def flush(self):
        pass

    def dump(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)
