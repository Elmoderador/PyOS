"""Driver gráfico del kernel: pantalla, ratón y eventos para PyOS LOOK.

Un único proceso puede ser dueño de la pantalla (gfx_open). Mientras lo es:
  * la consola de texto deja de pintar en pantalla (sigue saliendo por la UART);
  * el ratón PS/2 se activa; el kernel mueve el cursor él mismo en la interrupción,
    así responde aunque el proceso dueño vaya lento;
  * el proceso pinta con listas de órdenes (gfx_draw) que el kernel ejecuta con recorte;
  * gfx_poll entrega eventos de ratón y teclado (la consola en modo crudo), bloqueando
    hasta que haya alguno o venza el plazo.
Si el dueño muere, el kernel devuelve la pantalla a la consola de texto.
"""
from ..errors import KError, EBUSY, EINVAL, EPERM, EINTR
from ..proc.process import Block
from . import font8x19

ENODEV = 19
MAX_CMDS = 50000

# Cursor: X borde negro, o relleno blanco, espacio transparente.
CURSOR = [
    "X           ",
    "XX          ",
    "XoX         ",
    "XooX        ",
    "XoooX       ",
    "XooooX      ",
    "XoooooX     ",
    "XooooooX    ",
    "XoooooooX   ",
    "XooooooooX  ",
    "XoooooooooX ",
    "XooooooXXXXX",
    "XoooXooX    ",
    "XooXXooX    ",
    "XoX  XooX   ",
    "XX   XooX   ",
    "X     XooX  ",
    "      XooX  ",
    "       XX   ",
]
CUR_W, CUR_H = 12, len(CURSOR)
# columnas que la flecha cubre en cada fila [a, b): solo esas se guardan, pintan y restauran
CUR_SPAN = [(len(r) - len(r.lstrip()), len(r.rstrip())) for r in CURSOR]


def _build_glyph_runs():
    runs = {}
    for cp, rows in font8x19.GLYPHS.items():
        r = []
        for dy, bits in enumerate(rows):
            dx = 0
            while dx < 8:
                if bits & (0x80 >> dx):
                    s = dx
                    while dx < 8 and bits & (0x80 >> dx):
                        dx += 1
                    r.append((dy, s, dx - s))
                else:
                    dx += 1
        runs[cp] = r
    return runs


GLYPH_RUNS = _build_glyph_runs()
# Signos tipográficos que la fuente del firmware no trae: se dibujan con su equivalente.
for _cp, _sub in ((0x2014, "-"), (0x2013, "-"), (0x2018, "'"), (0x2019, "'"), (0x201C, '"'),
                  (0x201D, '"'), (0x2022, "\u00b7"), (0x2026, "."), (0x20AC, "E"), (0x2212, "-")):
    GLYPH_RUNS.setdefault(_cp, GLYPH_RUNS.get(ord(_sub), []))
FALLBACK = GLYPH_RUNS.get(0x2591) or GLYPH_RUNS[ord("?")]
GW, GH = font8x19.WIDTH, font8x19.HEIGHT


def _int(v, lo=-100000, hi=100000):
    if type(v) is bool or not isinstance(v, int) or not lo <= v <= hi:
        raise KError(EINVAL, "argumento gráfico inválido: %r" % (v,))
    return v


def _color(v):
    return _int(v, 0, 0xFFFFFF)


class Painter(object):
    """Primitivas con recorte sobre un framebuffer de la HAL."""

    def __init__(self, fb):
        self.fb = fb
        self.W, self.H = fb.width, fb.height
        self.clip = (0, 0, self.W, self.H)

    def set_clip(self, x, y, w, h):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.W, x + w), min(self.H, y + h)
        self.clip = (x0, y0, max(x0, x1), max(y0, y1))

    def rect(self, x, y, w, h, c):
        cx0, cy0, cx1, cy1 = self.clip
        x0, y0 = max(x, cx0), max(y, cy0)
        x1, y1 = min(x + w, cx1), min(y + h, cy1)
        if x0 >= x1 or y0 >= y1:
            return
        n = x1 - x0
        span = self.fb.span
        for yy in range(y0, y1):
            span(x0, yy, n, c)

    def frame(self, x, y, w, h, c, t=1):
        self.rect(x, y, w, t, c)
        self.rect(x, y + h - t, w, t, c)
        self.rect(x, y + t, t, h - 2 * t, c)
        self.rect(x + w - t, y + t, t, h - 2 * t, c)

    def text(self, x, y, s, fg, bg=None):
        if bg is not None:
            self.rect(x, y, GW * len(s), GH, bg)
        cx0, cy0, cx1, cy1 = self.clip
        if y >= cy1 or y + GH <= cy0:
            return
        inside_y = y >= cy0 and y + GH <= cy1
        span = self.fb.span
        for ch in s:
            if x >= cx1:
                break
            if x + GW > cx0 and ch != " ":
                runs = GLYPH_RUNS.get(ord(ch), FALLBACK)
                if inside_y and x >= cx0 and x + GW <= cx1:
                    for dy, dx, n in runs:
                        span(x + dx, y + dy, n, fg)
                else:
                    for dy, dx, n in runs:
                        yy = y + dy
                        if cy0 <= yy < cy1:
                            a, b = max(x + dx, cx0), min(x + dx + n, cx1)
                            if a < b:
                                span(a, yy, b - a, fg)
            x += GW

    def vgradient(self, x, y, w, h, c1, c2):
        if h <= 0:
            return
        r1, g1, b1 = c1 >> 16, (c1 >> 8) & 255, c1 & 255
        r2, g2, b2 = c2 >> 16, (c2 >> 8) & 255, c2 & 255
        cx0, cy0, cx1, cy1 = self.clip
        x0, x1 = max(x, cx0), min(x + w, cx1)
        if x0 >= x1:
            return
        # filas agrupadas por color: el búfer de color de la HAL se rellena una vez por color
        bycolor = {}
        n = x1 - x0
        for i in range(max(0, cy0 - y), min(h, cy1 - y)):
            t = i * 256 // max(1, h - 1)
            c = (((r1 + (r2 - r1) * t // 256) << 16) | ((g1 + (g2 - g1) * t // 256) << 8)
                 | (b1 + (b2 - b1) * t // 256))
            items = bycolor.get(c)
            if items is None:
                bycolor[c] = [(x0, y + i, n)]
            else:
                items.append((x0, y + i, n))
        for c, items in bycolor.items():
            self.fb.spans(items, c)

    def bitmap(self, x, y, rows, palette, scale=1):
        """rows: cadenas; palette: carácter -> color. Los caracteres sin color son transparentes."""
        cx0, cy0, cx1, cy1 = self.clip
        bycolor = {}
        for j, row in enumerate(rows):
            i = 0
            n = len(row)
            while i < n:
                c = palette.get(row[i])
                if c is None:
                    i += 1
                    continue
                s = i
                while i < n and palette.get(row[i]) == c:
                    i += 1
                for k in range(scale):
                    yy = y + j * scale + k
                    a, b = max(x + s * scale, cx0), min(x + i * scale, cx1)
                    if cy0 <= yy < cy1 and a < b:
                        bycolor.setdefault(c, []).append((a, yy, b - a))
        for c, items in bycolor.items():
            self.fb.spans(items, c)


    def image(self, x, y, w, h, data, scale=1):
        """data: bytes RGB (3 por píxel), w*h píxeles. Solo se convierte lo que cae dentro del
        recorte. Los tramos de un mismo color van como un solo span (en UEFI, una sola llamada
        a writemem); lo demás, píxel a píxel."""
        cx0, cy0, cx1, cy1 = self.clip
        fb = self.fb
        j0 = max(0, (cy0 - y) // scale)
        j1 = min(h, (cy1 - y + scale - 1) // scale)
        s0 = max(0, (cx0 - x) // scale)                 # columnas de origen visibles
        s1 = min(w, (cx1 - x + scale - 1) // scale)
        if j0 >= j1 or s0 >= s1:
            return
        for j in range(j0, j1):
            o = (j * w + s0) * 3
            row = data[o:o + (s1 - s0) * 3]
            cols = [row[i] << 16 | row[i + 1] << 8 | row[i + 2] for i in range(0, len(row), 3)]
            if scale > 1:
                cols = [c for c in cols for _ in range(scale)]
            base = x + s0 * scale                     # x de pantalla de cols[0]
            a = max(0, cx0 - base)
            b = min(len(cols), cx1 - base)
            if a >= b:
                continue
            for k in range(scale):
                yy = y + j * scale + k
                if not cy0 <= yy < cy1:
                    continue
                i = a
                pend_x = 0
                pend = []
                while i < b:
                    c = cols[i]
                    e = i + 1
                    while e < b and cols[e] == c:
                        e += 1
                    if e - i >= 4:
                        if pend:
                            fb.pixels(base + pend_x, yy, pend)
                            pend = []
                        fb.span(base + i, yy, e - i, c)
                    else:
                        if not pend:
                            pend_x = i
                        pend.extend(cols[i:e])
                    i = e
                if pend:
                    fb.pixels(base + pend_x, yy, pend)


class Gfx(object):
    def __init__(self, kernel, machine):
        self.k = kernel
        self.m = machine
        self.owner = None
        self.fb = None
        self.p = None
        self.waiter = None
        self.mouse_ok = False
        self.mx = self.my = 0
        self.buttons = 0
        self.mevents = []
        self.packet = []
        self.cur_saved = None           # (x, y, filas) bajo el cursor
        self.cursor_on = True
        self.frames = 0
        self.last_error = ""

    # ------------------------------------------------------------ propiedad
    def _check_owner(self, p):
        if self.owner != p.pid:
            raise KError(EPERM, "este proceso no tiene la pantalla (gfx_open)")

    def open(self, p):
        if self.owner is not None and self.owner != p.pid and self.owner in self.k.procs:
            raise KError(EBUSY, "la pantalla ya la usa el proceso %d" % self.owner)
        fbget = getattr(self.m, "framebuffer", None)
        if fbget is None:
            raise KError(ENODEV, "esta máquina no tiene framebuffer")
        try:
            fb = fbget()
        except Exception as e:
            self.last_error = str(e)
            self.k.log("gfx: " + self.last_error, "warn")
            raise KError(ENODEV, self.last_error)
        fb.begin()
        self.fb = fb
        self.p = Painter(fb)
        self.owner = p.pid
        con = getattr(self.m, "console", None)
        if con is not None:
            con.suspended = True
        mouse = getattr(self.m, "mouse", None)
        self.mouse_ok = bool(mouse is not None and mouse.mouse_enable(self.m.clock))
        self.mx, self.my = fb.width // 2, fb.height // 2
        self.buttons = 0
        self.mevents = []
        self.packet = []
        self.cur_saved = None
        self.k.log("gfx: pantalla para pid %d — %s %dx%d, copia %s, ratón %s" % (
            p.pid, getattr(fb, "desc", "?"), fb.width, fb.height,
            "rápida" if getattr(fb, "fast", False) else "lenta",
            self._mouse_desc() if self.mouse_ok else "no disponible"))
        return self.info()

    def _mouse_desc(self):
        return "PS/2 con rueda" if getattr(self.m.mouse, "wheel", False) else "PS/2"

    def info(self):
        fb = self.fb
        d = dict(fb.info()) if hasattr(fb, "info") else {}
        d.update({"width": fb.width, "height": fb.height, "mouse": self.mouse_ok,
                  "wheel": bool(self.mouse_ok and getattr(self.m.mouse, "wheel", False)),
                  "font": (GW, GH)})
        return d

    def close(self, pid):
        if self.owner != pid:
            return
        try:
            snap = getattr(self.fb, "snapshot", None)
            if snap is not None:
                snap()                          # solo framebuffers de pruebas
            self._cursor_hide()
            self.p.set_clip(0, 0, self.fb.width, self.fb.height)
            self.p.rect(0, 0, self.fb.width, self.fb.height, 0)
        finally:
            self.fb.end()
            mouse = getattr(self.m, "mouse", None)
            if mouse is not None and self.mouse_ok:
                mouse.mouse_disable(self.m.clock)
            self.owner = None
            self.waiter = None
            restore = getattr(self.m, "text_console_restore", None)
            if restore is not None:
                restore()
            self.k.log("gfx: pantalla devuelta a la consola de texto")

    def release(self, pid):
        if self.owner == pid:
            self.close(pid)

    # ------------------------------------------------------------ cursor
    def _cursor_hide(self):
        if self.cur_saved is None:
            return
        x, y, rows = self.cur_saved
        for j, row in enumerate(rows):
            if row:
                self.fb.pixels(x + CUR_SPAN[j][0], y + j, row)
        self.cur_saved = None

    def _cursor_show(self):
        if not self.cursor_on or self.cur_saved is not None:
            return
        fb = self.fb
        x, y = self.mx, self.my
        w = min(CUR_W, fb.width - x)
        rows = []
        for j in range(CUR_H):
            yy = y + j
            a, b = CUR_SPAN[j]
            b = min(b, w)
            if yy >= fb.height or a >= b:
                rows.append([])
                continue
            under = fb.read(x + a, yy, b - a)
            rows.append(under)
            line = CURSOR[j]
            out = [0x000000 if line[a + i] == "X" else (0xFFFFFF if line[a + i] == "o" else under[i])
                   for i in range(b - a)]
            if out != under:
                fb.pixels(x + a, yy, out)
        self.cur_saved = (x, y, rows)

    def _cursor_touched(self, cmds):
        """¿Puede este dibujo pisar el cursor? Solo si alguna región de recorte lo cruza
        (o si se dibuja sin recorte). Si no, el cursor se queda tal cual: ahorra ~250
        escrituras por fotograma."""
        if self.cur_saved is None:
            return False
        cx, cy = self.cur_saved[0], self.cur_saved[1]
        clipped = False
        for c in cmds:
            op = c[0] if c else None
            if op == "clip":
                clipped = True
                try:
                    x, y, w, h = c[1], c[2], c[3], c[4]
                    if x < cx + CUR_W and cx < x + w and y < cy + CUR_H and cy < y + h:
                        return True
                except (IndexError, TypeError):
                    return True
            elif op == "noclip":
                clipped = False
            elif not clipped:
                return True                     # dibujo a pantalla completa
        return False

    # ------------------------------------------------------------ dibujo
    def draw(self, p, cmds):
        self._check_owner(p)
        if not isinstance(cmds, (list, tuple)) or len(cmds) > MAX_CMDS:
            raise KError(EINVAL)
        P = self.p
        P.set_clip(0, 0, self.fb.width, self.fb.height)
        touched = self._cursor_touched(cmds)
        if touched:
            self._cursor_hide()
        n = 0
        try:
            for c in cmds:
                if not isinstance(c, (tuple, list)) or not c:
                    raise KError(EINVAL)
                op = c[0]
                if op == "rect":
                    P.rect(_int(c[1]), _int(c[2]), _int(c[3], 0), _int(c[4], 0), _color(c[5]))
                elif op == "text":
                    s = c[3]
                    if not isinstance(s, str) or len(s) > 4096:
                        raise KError(EINVAL)
                    P.text(_int(c[1]), _int(c[2]), s, _color(c[4]),
                           None if len(c) < 6 or c[5] is None else _color(c[5]))
                elif op == "frame":
                    P.frame(_int(c[1]), _int(c[2]), _int(c[3], 0), _int(c[4], 0), _color(c[5]),
                            _int(c[6], 1, 64) if len(c) > 6 else 1)
                elif op == "clip":
                    P.set_clip(_int(c[1]), _int(c[2]), _int(c[3], 0), _int(c[4], 0))
                elif op == "noclip":
                    P.set_clip(0, 0, self.fb.width, self.fb.height)
                elif op == "vgrad":
                    P.vgradient(_int(c[1]), _int(c[2]), _int(c[3], 0), _int(c[4], 0),
                                _color(c[5]), _color(c[6]))
                elif op == "bitmap":
                    rows, pal = c[3], c[4]
                    if (not isinstance(rows, (list, tuple)) or len(rows) > 256
                            or not all(isinstance(r, str) and len(r) <= 256 for r in rows)
                            or not isinstance(pal, dict)):
                        raise KError(EINVAL)
                    palette = {}
                    for k, v in pal.items():
                        if not isinstance(k, str) or len(k) != 1:
                            raise KError(EINVAL)
                        palette[k] = _color(v)
                    P.bitmap(_int(c[1]), _int(c[2]), rows, palette,
                             _int(c[5], 1, 16) if len(c) > 5 else 1)
                elif op == "image":
                    w, h, data = _int(c[3], 0, 4096), _int(c[4], 0, 4096), c[5]
                    if not isinstance(data, (bytes, bytearray)) or len(data) != w * h * 3 \
                            or w * h > 2 * 1024 * 1024:
                        raise KError(EINVAL)
                    P.image(_int(c[1]), _int(c[2]), w, h, bytes(data),
                            _int(c[6], 1, 16) if len(c) > 6 else 1)
                else:
                    raise KError(EINVAL, "orden gráfica desconocida: %r" % (op,))
                n += 1
        finally:
            self._cursor_show()
        self.frames += 1
        return n

    # ------------------------------------------------------------ ratón
    def irq_pending(self):
        if self.owner is None or not self.mouse_ok:
            return False
        data = self.m.mouse.mouse_bytes()
        if not data:
            return False
        moved = False
        psize = getattr(self.m.mouse, "packet_size", 3)
        for b in data:
            if not self.packet and not b & 0x08:
                continue                        # resincronización: el primer byte lleva el bit 3
            self.packet.append(b)
            if len(self.packet) == psize:
                b0, bx, by = self.packet[:3]
                dz = 0
                if psize == 4:
                    dz = self.packet[3] & 0x0F
                    if dz & 0x08:
                        dz -= 16                # 4 bits con signo
                self.packet = []
                if b0 & 0xC0:
                    continue                    # desbordamiento: paquete descartado
                dx = bx - 256 if b0 & 0x10 else bx
                dy = by - 256 if b0 & 0x20 else by
                if abs(dx) > 6:
                    dx *= 2
                if abs(dy) > 6:
                    dy *= 2
                nx = min(max(self.mx + dx, 0), self.fb.width - 1)
                ny = min(max(self.my - dy, 0), self.fb.height - 1)
                btn = b0 & 7
                if (nx, ny) != (self.mx, self.my):
                    moved = True
                self.mx, self.my = nx, ny
                ev = (nx, ny, btn, int(self.k.clock() * 1000), dz)   # marca de tiempo del kernel
                if self.mevents and self.mevents[-1][2] == btn and btn == self.buttons \
                        and not dz and not self.mevents[-1][4]:
                    self.mevents[-1] = ev           # movimientos seguidos: solo el último
                else:
                    self.mevents.append(ev)
                self.buttons = btn
        if moved:
            self._cursor_hide()
            self._cursor_show()
        return True

    def interrupt(self):
        self.notify()

    def notify(self):
        w = self.waiter
        if w is not None and w.pid in self.k.procs:
            self.waiter = None
            self.k.wake(w)

    # ------------------------------------------------------------ eventos
    def poll(self, p, timeout_ms):
        self._check_owner(p)
        tty = self.k.tty
        keys = tty.read_nowait(4096) if tty.raw_owner == p.pid else b""
        if self.mevents or keys or timeout_ms <= 0:
            p.deadline = None
            ev = {"mouse": self.mevents, "keys": keys, "pos": (self.mx, self.my, self.buttons)}
            self.mevents = []
            return ev
        now = self.k.clock()
        if p.deadline is None:
            p.deadline = now + timeout_ms / 1000.0
        if now >= p.deadline:
            p.deadline = None
            return {"mouse": [], "keys": b"", "pos": (self.mx, self.my, self.buttons)}
        if p.pending_signals:
            p.deadline = None
            raise KError(EINTR)
        self.waiter = p
        raise Block(self.k.sleep_wq, p.deadline)

    def set_cursor(self, p, visible=None, pos=None):
        self._check_owner(p)
        if pos is not None:
            self._cursor_hide()
            self.mx = min(max(_int(pos[0]), 0), self.fb.width - 1)
            self.my = min(max(_int(pos[1]), 0), self.fb.height - 1)
        if visible is not None:
            self.cursor_on = bool(visible)
            if not self.cursor_on:
                self._cursor_hide()
        self._cursor_show()
        return 0

    def text_width(self, s):
        return GW * len(s)

    def proc_text(self):
        if self.owner is None:
            return "gfx: libre (consola de texto)\n" + (
                "último error: %s\n" % self.last_error if self.last_error else "")
        i = self.info()
        return ("dueño: pid %d\nadaptador: %s\nresolución: %dx%d\ncopia: %s\nratón: %s\n"
                "fotogramas: %d\nllamadas al framebuffer: %d\n" % (
                    self.owner, i.get("adapter", "?"), i["width"], i["height"], i.get("copy", "?"),
                    self._mouse_desc() if self.mouse_ok else "no", self.frames, getattr(self.fb, "calls", 0)))
