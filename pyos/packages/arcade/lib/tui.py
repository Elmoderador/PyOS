# /lib/tui.py — pantalla completa para juegos de PyOS. Se carga con include("/lib/tui.py").
#
# Doble búfer de caracteres: el juego dibuja en `back` con put()/fill() y present()
# envía al terminal solo los tramos de fila que han cambiado (secuencias ANSI que
# el kernel traduce a posiciones del cursor en la consola UEFI).
# Teclado en modo crudo y sin bloqueo: keys() devuelve "up" "down" "left" "right"
# "enter" "esc" "space" o el carácter pulsado.

BLOCK = "█"     # █  (los glifos de dibujo están en la fuente obligatoria de UEFI)
SHADE = "░"     # ░
H, V = "─", "│"
TL, TR, BL, BR = "┌", "┐", "└", "┘"
DH, DV = "═", "║"
DTL, DTR, DBL, DBR = "╔", "╗", "╚", "╝"
UP, DOWN, LEFT, RIGHT = "▲", "▼", "◄", "►"

_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}


class Screen:
    def __init__(self, min_cols=40, min_rows=20):
        cols, rows = ttyctl("size")
        if cols < min_cols or rows < min_rows:
            raise RuntimeError("pantalla demasiado pequeña: %dx%d (hace falta %dx%d)"
                               % (cols, rows, min_cols, min_rows))
        self.cols = cols
        self.rows = rows
        self.back = [[" "] * cols for _ in range(rows)]
        self.front = [[" "] * cols for _ in range(rows)]
        self.pending = b""
        ttyctl("raw", True)
        write(STDOUT, "\x1b[?25l\x1b[0m\x1b[2J")

    # ---------------------------------------------------------------- dibujo
    def clear(self):
        for row in self.back:
            row[:] = [" "] * self.cols

    def put(self, r, c, text):
        if r < 0 or r >= self.rows:
            return
        if c < 0:
            text = text[-c:]
            c = 0
        room = self.cols - c
        if r == self.rows - 1:
            room -= 1                         # la última celda haría desplazar la pantalla
        if room <= 0:
            return
        text = text[:room]
        self.back[r][c:c + len(text)] = list(text)

    def center(self, r, text):
        self.put(r, (self.cols - len(text)) // 2, text)

    def fill(self, r, c, h, w, ch=" "):
        for y in range(r, r + h):
            self.put(y, c, ch * w)

    def box(self, r, c, h, w, double=False):
        tl, tr, bl, br, hz, vt = (DTL, DTR, DBL, DBR, DH, DV) if double else (TL, TR, BL, BR, H, V)
        self.put(r, c, tl + hz * (w - 2) + tr)
        for y in range(r + 1, r + h - 1):
            self.put(y, c, vt)
            self.put(y, c + w - 1, vt)
        self.put(r + h - 1, c, bl + hz * (w - 2) + br)

    def present(self):
        out = []
        cols = self.cols
        for r in range(self.rows):
            b = self.back[r]
            f = self.front[r]
            if b == f:
                continue
            lo = 0
            while b[lo] == f[lo]:
                lo += 1
            hi = cols - 1
            while b[hi] == f[hi]:
                hi -= 1
            out.append("\x1b[%d;%dH" % (r + 1, lo + 1))
            out.append("".join(b[lo:hi + 1]))
            f[lo:hi + 1] = b[lo:hi + 1]
        if out:
            out.append("\x1b[%d;%dH" % (self.rows, 1))   # cursor aparcado abajo a la izquierda
            write(STDOUT, "".join(out))

    # ---------------------------------------------------------------- teclado
    def keys(self):
        data = self.pending + ttyctl("read", 64)
        self.pending = b""
        res = []
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1B:
                if i + 2 < n and data[i + 1] == 0x5B:
                    k = chr(data[i + 2])
                    if k in _ARROWS:
                        res.append(_ARROWS[k])
                        i += 3
                        continue
                    j = i + 2                     # otra secuencia (Supr, Inicio...): se salta
                    while j < n and not (0x40 <= data[j] <= 0x7E):
                        j += 1
                    i = j + 1
                    continue
                if i + 1 < n and data[i + 1] == 0x5B:
                    self.pending = data[i:]       # secuencia partida entre lecturas
                    break
                res.append("esc")
            elif b in (0x0D, 0x0A):
                res.append("enter")
            elif b == 0x20:
                res.append("space")
            elif b == 0x7F or b == 0x08:
                res.append("backspace")
            elif b >= 0x20:
                res.append(chr(b).lower())
            i += 1
        return res

    def wait_key(self):
        while True:
            ks = self.keys()
            if ks:
                return ks[0]
            sleep_ms(30)

    def close(self):
        write(STDOUT, "\x1b[0m\x1b[2J\x1b[H\x1b[?25h")
        ttyctl("raw", False)


# -------------------------------------------------------------------- utilidades
class Rng:
    """xorshift32 sembrado con /dev/random."""

    def __init__(self):
        fd = open("/dev/random")
        b = read(fd, 4)
        close(fd)
        self.s = (b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)) or 0x2545F491

    def next(self):
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x
        return x

    def randint(self, a, b):
        return a + self.next() % (b - a + 1)

    def choice(self, seq):
        return seq[self.next() % len(seq)]

    def chance(self, p):
        return (self.next() % 10000) < p * 10000


class Clock:
    """Ritmo fijo de fotogramas sin consumir CPU de más (sleep entre fotogramas)."""

    def __init__(self, fps):
        self.frame = 1000 // fps
        self.t = uptime_ms()

    def tick(self):
        self.t += self.frame
        now = uptime_ms()
        if self.t > now:
            sleep_ms(self.t - now)
        else:
            self.t = now                      # vamos tarde: no acumular retraso


SCORES = "/var/games"


def highscore(game, score=None):
    """Devuelve el récord de `game`; si `score` lo supera, lo guarda."""
    path = SCORES + "/" + game
    best = 0
    try:
        best = int(read_file(path).decode().strip() or "0")
    except (OSError, ValueError):
        pass
    if score is not None and score > best:
        if not exists(SCORES):
            mkdir(SCORES)
        write_file(path, str(score) + "\n")
        sync()
    return best


def run_game(play):
    """Ejecuta play(scr) restaurando siempre la consola (también ante errores)."""
    scr = Screen()
    try:
        result = play(scr)
    finally:
        scr.close()
    return result


def game_over(scr, title, score, best, extra=""):
    """Pantalla final. Devuelve True si el jugador quiere repetir."""
    w = 34
    r = scr.rows // 2 - 4
    c = (scr.cols - w) // 2
    scr.fill(r, c, 8, w, " ")
    scr.box(r, c, 8, w, True)
    scr.put(r + 1, c + (w - len(title)) // 2, title)
    line = "Puntos: %d" % score
    scr.put(r + 3, c + (w - len(line)) // 2, line)
    line = ("¡NUEVO RÉCORD!" if score > best else "Récord: %d" % best)
    scr.put(r + 4, c + (w - len(line)) // 2, line)
    if extra:
        scr.put(r + 5, c + (w - len(extra)) // 2, extra)
    line = "Intro: otra   Q: salir"
    scr.put(r + 6, c + (w - len(line)) // 2, line)
    scr.present()
    sleep_ms(400)
    scr.keys()                                 # descarta teclas que venían del juego
    while True:
        k = scr.wait_key()
        if k in ("enter", "space", "r"):
            return True
        if k in ("q", "esc"):
            return False
