# /lib/look/apps2.py — Calculadora, Paint y Visor de imágenes de PyOS LOOK.
include("/lib/look/image.py")


# ================================================================== Calculadora
class CalcError(Exception):
    pass


def calc_tokens(s):
    out = []
    i = 0
    s = s.replace("×", "*").replace("÷", "/").replace(",", ".")
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c.isdigit() or c == ".":
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] == "."):
                j += 1
            try:
                out.append(float(s[i:j]))
            except ValueError:
                raise CalcError("número mal escrito")
            i = j
        elif s.startswith("**", i):
            out.append("^")
            i += 2
        elif c in "+-*/%^()":
            out.append(c)
            i += 1
        else:
            raise CalcError("carácter no válido: %s" % c)
    return out


class CalcParser:
    """expr := term (('+'|'-') term)* ; term := unary (('*'|'/'|'%') unary)* ;
    unary := '-' unary | power ; power := atom ('^' unary)?  (asociativa por la derecha)"""

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        v = self.peek()
        self.i += 1
        return v

    def parse(self):
        if not self.t:
            raise CalcError("vacío")
        v = self.expr()
        if self.peek() is not None:
            raise CalcError("sobra %s" % self.peek())
        return v

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            if self.take() == "+":
                v = v + self.term()
            else:
                v = v - self.term()
        return v

    def term(self):
        v = self.unary()
        while self.peek() in ("*", "/", "%"):
            op = self.take()
            r = self.unary()
            if op == "*":
                v = v * r
            elif r == 0:
                raise CalcError("división por cero")
            elif op == "/":
                v = v / r
            else:
                v = v % r
        return v

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        v = self.atom()
        if self.peek() == "^":
            self.take()
            e = self.unary()
            if abs(e) > 1000 or (v == 0 and e < 0):
                raise CalcError("potencia fuera de rango")
            v = v ** e
            if isinstance(v, complex):
                raise CalcError("resultado complejo")
        return v

    def atom(self):
        t = self.take()
        if t == "(":
            v = self.expr()
            if self.take() != ")":
                raise CalcError("falta )")
            return v
        if isinstance(t, float):
            return t
        raise CalcError("falta un número")


def calc_eval(s):
    return CalcParser(calc_tokens(s)).parse()


def calc_fmt(v):
    if v != v or v in (float("inf"), float("-inf")):
        raise CalcError("fuera de rango")
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = "%.12g" % v
    return s


class Calculator(Window):
    icon = "calc"
    resizable = False
    KEYS = [["C", "(", ")", "/"],
            ["7", "8", "9", "*"],
            ["4", "5", "6", "-"],
            ["1", "2", "3", "+"],
            ["0", ".", "<", "="]]

    def __init__(self):
        Window.__init__(self, "Calculadora", 300, 410)
        self.expr = ""
        self.prev = ""
        self.err = False
        bw, bh, gap = 64, 48, 6
        for r, row in enumerate(self.KEYS):
            for c, k in enumerate(row):
                self.add_button(10 + c * (bw + gap), 96 + r * (bh + gap), bw, bh,
                                "←" if k == "<" else ("×" if k == "*" else ("÷" if k == "/" else k)),
                                self._press(k), k == "=")

    def _press(self, k):
        def f():
            self.key(k)
        return f

    def key(self, k):
        if self.err and k not in ("C", "<"):
            self.expr = ""
            self.err = False
        if k == "C":
            self.expr = ""
            self.prev = ""
            self.err = False
        elif k == "<":
            self.expr = "" if self.err else self.expr[:-1]
            self.err = False
        elif k == "=":
            if self.expr:
                try:
                    res = calc_fmt(calc_eval(self.expr))
                    self.prev = self.expr + " ="
                    self.expr = res
                except (CalcError, OverflowError) as e:
                    self.prev = self.expr
                    self.expr = "Error: %s" % e
                    self.err = True
        elif len(self.expr) < 64:
            self.expr += k
        self.redraw()

    def draw_content(self, g, x, y, w, h):
        g.append(("rect", x + 10, y + 10, w - 20, 74, T["field"]))
        g.append(("frame", x + 10, y + 10, w - 20, 74, T["btn_edge"], 1))
        p = clip_text(self.prev, w - 36) if len(self.prev) * FW <= w - 36 else "…" + self.prev[-((w - 44) // FW):]
        g.append(("text", x + w - 18 - FW * len(p), y + 18, p, T["muted"], None))
        e = self.expr or "0"
        vis = (w - 40) // (FW * 2)
        if len(e) <= vis:
            for dx in (0, 1):
                g.append(("text", x + w - 18 - FW * len(e) * 1 - dx, y + 50, e,
                          T["danger"] if self.err else T["text"], None))
        else:
            e = e[-((w - 36) // FW):]
            g.append(("text", x + w - 18 - FW * len(e), y + 50, e, T["danger"] if self.err else T["text"], None))

    def on_key(self, k):
        m = {"enter": "=", "backspace": "<", "esc": "C", "delete": "C", "x": "*", "X": "*",
             ",": "."}
        k = m.get(k, k)
        if k in "0123456789.+-*/%^()" and len(k) == 1 or k in ("=", "<", "C"):
            self.key(k)


# ================================================================== Paint
PAINT_COLORS = [0x000000, 0x404040, 0x808080, 0xFFFFFF, 0x7F1D1D, 0xEF4444, 0xF97316, 0xFACC15,
                0x166534, 0x22C55E, 0x0E7490, 0x38BDF8, 0x1E3A8A, 0x3B82F6, 0x7E22CE, 0xEC4899]
PAINT_TOOLS = [("lapiz", "Lápiz"), ("goma", "Goma"), ("linea", "Línea"), ("rect", "Rect"),
               ("caja", "Caja"), ("cubo", "Cubo")]
SIZES = (1, 3, 7, 13)


def rgb3(c):
    return bytes([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF])


class Paint(Window):
    icon = "paint"
    closing_ok = False
    min_w = 520
    min_h = 380
    LEFT = 72
    TOP = 44

    def __init__(self, path=None):
        Window.__init__(self, "Paint", 760, 560)
        self.path = path
        self.cw, self.chh = 640, 400
        self.px = bytearray(b"\xff" * (3 * self.cw * self.chh))
        self.undo = None
        self.tool = "lapiz"
        self.color = 0x000000
        self.size = 3
        self.drawing = False
        self.last = None
        self.start = None
        self.preview = None
        self.vx = self.vy = 0
        self.dirty = False
        self.msg = "rueda: desplazar"
        self.add_button(8, 8, 70, 28, "Nuevo", self.new)
        self.add_button(82, 8, 70, 28, "Abrir", self.open_dialog)
        self.add_button(156, 8, 80, 28, "Guardar", self.save_dialog, True)
        self.add_button(240, 8, 90, 28, "Deshacer", self.do_undo)
        if path:
            self.load(path)

    # ---------------------------------------------------------- ficheros
    def load(self, path):
        try:
            w, h, px = load(path)
        except (OSError, ValueError) as e:
            self.msg = "No se pudo abrir %s: %s" % (path, e)
            return
        if w * h > 1024 * 1024:
            self.msg = "Imagen demasiado grande para editar (máx. 1 Mpx)"
            return
        self.cw, self.chh, self.px = w, h, bytearray(px)
        self.path = path
        self.vx = self.vy = 0
        self.undo = None
        self.dirty = False
        self.title = "Paint - " + path
        self.msg = "%s (%dx%d)" % (path, w, h)
        self.redraw()

    def new(self):
        def go():
            self.cw, self.chh = 640, 400
            self.px = bytearray(b"\xff" * (3 * self.cw * self.chh))
            self.path = None
            self.undo = None
            self.dirty = False
            self.title = "Paint"
            self.vx = self.vy = 0
            self.redraw()
        if self.dirty:
            self.wm.message("Paint", "¿Descartar el dibujo actual?", [("Descartar", go), ("Cancelar", None)], 1)
        else:
            go()

    def open_dialog(self):
        def done(v):
            if v:
                self.load(v)
                self.redraw()
        self.wm.add(Prompt("Abrir imagen", "Ruta del BMP/PPM:", self.path or "/root/", done))

    def save_dialog(self):
        def done(v):
            if not v:
                return
            if not v.lower().endswith(".bmp"):
                v += ".bmp"
            try:
                save_bmp(v, self.cw, self.chh, self.px)
                self.path = v
                self.dirty = False
                self.title = "Paint - " + v
                self.msg = "Guardado %s" % v
                self.wm.toast("Paint: guardado\n%s" % v)
            except OSError as e:
                self.msg = "Error al guardar: %s" % e
            if self.wm is not None:
                self.wm.damage(self.wm.taskbar_rect())
            self.redraw()
        self.wm.add(Prompt("Guardar imagen", "Guardar como (BMP):", self.path or "/root/dibujo.bmp", done))

    def do_undo(self):
        if self.undo is not None:
            self.cw, self.chh, self.px = self.undo
            self.undo = None
            self.redraw()

    def unsaved(self):
        return self.dirty

    def on_close(self):
        if self.dirty and not self.closing_ok:
            def go():
                self.closing_ok = True
                self.close()
            self.wm.message("Paint", "El dibujo tiene cambios sin guardar. ¿Cerrar igualmente?",
                            [("Cerrar", go), ("Cancelar", None)], 1)
            return False
        return True

    # ---------------------------------------------------------- geometría
    def view(self):
        cx, cy, cw, ch = self.content()
        return (self.LEFT, self.TOP, cw - self.LEFT - 8, ch - self.TOP - 44)

    def to_canvas(self, x, y):
        ax, ay, aw, ah = self.view()
        return x - ax + self.vx, y - ay + self.vy

    def damage_canvas(self, x0, y0, x1, y1):
        """Daña solo el trozo de pantalla del rectángulo del lienzo (x0,y0)-(x1,y1)."""
        if self.wm is None:
            return
        ax, ay, aw, ah = self.view()
        cx, cy, cw, ch = self.content()
        r = (cx + ax + min(x0, x1) - self.vx - 1, cy + ay + min(y0, y1) - self.vy - 1,
             abs(x1 - x0) + 3, abs(y1 - y0) + 3)
        r = rinter(r, (cx + ax, cy + ay, aw, ah))
        if r is not None:
            self.wm.damage(r)

    # ---------------------------------------------------------- pintar en el lienzo
    def stamp(self, x, y, s, col):
        W, H = self.cw, self.chh
        h = s // 2
        x0, x1 = max(0, x - h), min(W, x - h + s)
        if x0 >= x1:
            return
        run = col * (x1 - x0)
        for yy in range(max(0, y - h), min(H, y - h + s)):
            o = (yy * W + x0) * 3
            self.px[o:o + len(run)] = run

    def fill_rect(self, x0, y0, x1, y1, col):
        W, H = self.cw, self.chh
        x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1) + 1)
        y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1) + 1)
        if x0 >= x1:
            return
        run = col * (x1 - x0)
        for yy in range(y0, y1):
            o = (yy * W + x0) * 3
            self.px[o:o + len(run)] = run

    def line(self, x0, y0, x1, y1, s, col):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        step = max(1, s // 2)
        n = 0
        while True:
            if n % step == 0 or (x0 == x1 and y0 == y1):
                self.stamp(x0, y0, s, col)
            n += 1
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def rect_outline(self, x0, y0, x1, y1, s, col):
        h = s // 2
        a, b = min(x0, x1), max(x0, x1)
        c, d = min(y0, y1), max(y0, y1)
        self.fill_rect(a - h, c - h, b + h, c - h + s - 1, col)
        self.fill_rect(a - h, d - h, b + h, d - h + s - 1, col)
        self.fill_rect(a - h, c - h, a - h + s - 1, d + h, col)
        self.fill_rect(b - h, c - h, b - h + s - 1, d + h, col)

    def _run_end(self, row, o, t, limit):
        """Primer índice de píxel >= o/3 (en `row`, en píxeles) que NO es t, hasta `limit`.
        Búsqueda galopante con comparaciones de bytes nativas: O(log n) pasos en la PVM."""
        lo = o
        n = 1
        while lo + n <= limit and row[3 * lo:3 * (lo + n)] == t * n:
            lo += n
            n *= 2
        while n > 1:
            n //= 2
            if lo + n <= limit and row[3 * lo:3 * (lo + n)] == t * n:
                lo += n
        return lo

    def _run_start(self, row, o, t):
        """Primer píxel de la racha de t que acaba en o (incluido)."""
        hi = o + 1
        n = 1
        while hi - n >= 0 and row[3 * (hi - n):3 * hi] == t * n:
            hi -= n
            n *= 2
        while n > 1:
            n //= 2
            if hi - n >= 0 and row[3 * (hi - n):3 * hi] == t * n:
                hi -= n
        return hi

    def flood(self, x, y, col):
        W, H = self.cw, self.chh
        if not (0 <= x < W and 0 <= y < H):
            return None
        o = (y * W + x) * 3
        t = bytes(self.px[o:o + 3])
        if t == col:
            return None
        bbox = [x, y, x, y]
        stack = [(x, y)]
        count = 0
        while stack:
            sx, sy = stack.pop()
            row = self.px[sy * W * 3:(sy + 1) * W * 3]
            if row[3 * sx:3 * sx + 3] != t:
                continue
            l = self._run_start(row, sx, t)
            r = self._run_end(row, sx, t, W)          # exclusivo
            o = (sy * W + l) * 3
            self.px[o:o + 3 * (r - l)] = col * (r - l)
            count += r - l
            bbox[0] = min(bbox[0], l)
            bbox[2] = max(bbox[2], r - 1)
            bbox[1] = min(bbox[1], sy)
            bbox[3] = max(bbox[3], sy)
            for ny in (sy - 1, sy + 1):
                if not 0 <= ny < H:
                    continue
                nrow = self.px[ny * W * 3:(ny + 1) * W * 3]
                p = l
                while p < r:
                    if nrow[3 * p:3 * p + 3] == t:
                        e = self._run_end(nrow, p, t, r)
                        stack.append((p, ny))
                        p = e
                    else:
                        # salta hasta la siguiente aparición alineada de t
                        k = nrow.find(t, 3 * p + 1)
                        while k >= 0 and k % 3:
                            k = nrow.find(t, k + 1)
                        if k < 0:
                            break
                        p = k // 3
        return bbox

    # ---------------------------------------------------------- eventos
    def on_mouse(self, kind, x, y, b):
        ax, ay, aw, ah = self.view()
        cx, cy, cw, ch = self.content()
        inside = ax <= x < ax + aw and ay <= y < ay + ah
        if kind == "wheel":
            self.vy = max(0, min(max(0, self.chh - ah), self.vy + 40 * b))
            self.redraw()
            return
        if kind == "down":
            # herramientas
            for i, (tid, label) in enumerate(PAINT_TOOLS):
                if rin((8, 44 + i * 34, 56, 30), x, y):
                    self.tool = tid
                    self.redraw()
                    return
            for i, s in enumerate(SIZES):
                if rin((8, 272 + i * 26, 56, 22), x, y):
                    self.size = s
                    self.redraw()
                    return
            for i, c in enumerate(PAINT_COLORS):
                if rin((self.LEFT + 44 + i * 26, ch - 34, 22, 22), x, y):
                    self.color = c
                    self.redraw()
                    return
            if not inside:
                return
            px, py = self.to_canvas(x, y)
            if not (0 <= px < self.cw and 0 <= py < self.chh):
                return
            self.undo = (self.cw, self.chh, bytearray(self.px))
            self.dirty = True
            col = rgb3(0xFFFFFF if self.tool == "goma" else self.color)
            if self.tool in ("lapiz", "goma"):
                self.drawing = True
                self.last = (px, py)
                s = self.size if self.tool == "lapiz" else max(9, self.size * 2)
                self.stamp(px, py, s, col)
                self.damage_canvas(px - s, py - s, px + s, py + s)
            elif self.tool == "cubo":
                t0 = uptime_ms()
                bb = self.flood(px, py, col)
                if bb:
                    self.damage_canvas(bb[0], bb[1], bb[2] + 1, bb[3] + 1)
                    self.msg = "relleno en %d ms" % (uptime_ms() - t0)
                    self.redraw_status()
            else:
                self.drawing = True
                self.start = (px, py)
                self.preview = (px, py, px, py)
        elif kind == "drag" and self.drawing:
            px, py = self.to_canvas(x, y)
            if self.tool in ("lapiz", "goma"):
                col = rgb3(0xFFFFFF if self.tool == "goma" else self.color)
                s = self.size if self.tool == "lapiz" else max(9, self.size * 2)
                lx, ly = self.last
                self.line(lx, ly, px, py, s, col)
                self.damage_canvas(min(lx, px) - s, min(ly, py) - s, max(lx, px) + s, max(ly, py) + s)
                self.last = (px, py)
            else:
                old = self.preview
                self.preview = (self.start[0], self.start[1], px, py)
                s = self.size
                for p in (old, self.preview):
                    self.damage_canvas(min(p[0], p[2]) - s, min(p[1], p[3]) - s,
                                       max(p[0], p[2]) + s, max(p[1], p[3]) + s)
        elif kind == "up" and self.drawing:
            self.drawing = False
            if self.preview is not None:
                x0, y0, x1, y1 = self.preview
                col = rgb3(self.color)
                if self.tool == "linea":
                    self.line(x0, y0, x1, y1, self.size, col)
                elif self.tool == "rect":
                    self.rect_outline(x0, y0, x1, y1, self.size, col)
                elif self.tool == "caja":
                    self.fill_rect(x0, y0, x1, y1, col)
                s = self.size
                self.damage_canvas(min(x0, x1) - s, min(y0, y1) - s, max(x0, x1) + s, max(y0, y1) + s)
                self.preview = None

    def redraw_status(self):
        if self.wm is None:
            return
        cx, cy, cw, ch = self.content()
        self.wm.damage((cx, cy + ch - 40, cw, 40))

    def on_key(self, k):
        if k == "ctrl-z":
            self.do_undo()
        elif k == "ctrl-s":
            self.save_dialog()
        elif k == "ctrl-o":
            self.open_dialog()
        elif k in ("1", "2", "3", "4", "5", "6"):
            self.tool = PAINT_TOOLS[int(k) - 1][0]
            self.redraw()
        elif k in ("pgdn", "down"):
            self.on_mouse("wheel", 0, 0, 1)
        elif k in ("pgup", "up"):
            self.on_mouse("wheel", 0, 0, -1)

    # ---------------------------------------------------------- dibujo
    def draw_content(self, g, x, y, w, h):
        ax, ay, aw, ah = self.view()
        for i, (tid, label) in enumerate(PAINT_TOOLS):
            d_button(g, x + 8, y + 44 + i * 34, 56, 30, label, self.tool == tid)
        g.append(("text", x + 8, y + 252, "Grosor", T["muted"], None))
        for i, s in enumerate(SIZES):
            r = (x + 8, y + 272 + i * 26, 56, 22)
            g.append(("rect",) + r + (T["sel"] if s == self.size else T["btn"],))
            g.append(("rect", x + 14, y + 272 + i * 26 + 11 - s // 2, 44, s, T["text"]))
        # lienzo
        g.append(("rect", x + ax, y + ay, aw, ah, T["line"]))
        g.append(("clip_push", x + ax, y + ay, aw, ah))
        vw = min(self.cw - self.vx, aw)
        vh = min(self.chh - self.vy, ah)
        if vw > 0 and vh > 0:
            if self.vx == 0 and self.vy == 0 and vw == self.cw and vh == self.chh:
                buf = self.px
            else:
                rows = []
                for j in range(self.vy, self.vy + vh):
                    o = (j * self.cw + self.vx) * 3
                    rows.append(bytes(self.px[o:o + 3 * vw]))
                buf = b"".join(rows)
            g.append(("image", x + ax, y + ay, vw, vh, bytes(buf), 1))
        if self.preview is not None:
            x0, y0, x1, y1 = self.preview
            sx, sy = x + ax - self.vx, y + ay - self.vy
            c = self.color
            if self.tool == "caja":
                g.append(("rect", sx + min(x0, x1), sy + min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1, c))
            elif self.tool == "rect":
                g.append(("frame", sx + min(x0, x1), sy + min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1, c,
                          max(1, self.size)))
            else:
                n = max(abs(x1 - x0), abs(y1 - y0)) // 3 + 1
                for i in range(n + 1):
                    px = x0 + (x1 - x0) * i // n
                    py = y0 + (y1 - y0) * i // n
                    g.append(("rect", sx + px - self.size // 2, sy + py - self.size // 2,
                              max(2, self.size), max(2, self.size), c))
        g.append(("clip_pop",))
        # paleta
        g.append(("rect", x + self.LEFT, y + h - 36, 34, 26, self.color))
        g.append(("frame", x + self.LEFT, y + h - 36, 34, 26, T["text"], 1))
        for i, c in enumerate(PAINT_COLORS):
            r = (x + self.LEFT + 44 + i * 26, y + h - 34, 22, 22)
            g.append(("rect",) + r + (c,))
            g.append(("frame",) + r + (T["accent"] if c == self.color else T["btn_edge"], 2 if c == self.color else 1))
        mx = self.LEFT + 44 + 16 * 26 + 8
        g.append(("text", x + mx, y + h - 32, clip_text(self.msg, w - mx - 8), T["muted"], None))
        g.append(("text", x + 340, y + 13, clip_text("%dx%d  %s" % (self.cw, self.chh, self.path or "sin guardar"),
                                                     w - 350), T["muted"], None))


# ================================================================== Visor de imágenes
IMG_EXT = (".bmp", ".ppm", ".pgm")


class ImageViewer(Window):
    icon = "image"
    min_w = 400
    min_h = 260

    def __init__(self, path=None):
        Window.__init__(self, "Imágenes", 720, 540)
        self.path = path
        self.img = None
        self.err = ""
        self.zoom = 0             # 0 = ajustar; >0 ampliar xN; <0 reducir /N
        self.disp = None
        self.ox = self.oy = 0
        self.drag0 = None
        self.add_button(8, 8, 34, 28, "<", self.prev)
        self.add_button(46, 8, 34, 28, ">", self.next)
        self.add_button(92, 8, 34, 28, "-", self.zoom_out)
        self.add_button(130, 8, 34, 28, "+", self.zoom_in)
        self.add_button(168, 8, 74, 28, "Ajustar", self.fit)
        self.add_button(246, 8, 64, 28, "Abrir", self.open_dialog)
        self.add_button(314, 8, 74, 28, "Editar", self.edit)
        if path:
            self.load(path)

    def area(self):
        cx, cy, cw, ch = self.content()
        return (0, 44, cw, ch - 44 - 26)

    def load(self, path):
        self.path = path
        self.img = None
        self.disp = None
        self.err = ""
        try:
            self.img = load(path)
        except (OSError, ValueError) as e:
            self.err = str(e)
        self.zoom = 0
        self.ox = self.oy = 0
        self.title = "Imágenes - " + path.rsplit("/", 1)[-1]
        if self.wm is not None:
            self.wm.damage(self.wm.taskbar_rect())
        self.prepare()
        self.redraw()

    def factor(self):
        """(reducción entera, ampliación entera) efectivos."""
        if self.img is None:
            return 1, 1
        w, h, px = self.img
        ax, ay, aw, ah = self.area()
        z = self.zoom
        if z == 0:
            k = max(1, -(-w // max(1, aw)), -(-h // max(1, ah)))
            if k > 1:
                return k, 1
            s = max(1, min(aw // max(1, w), ah // max(1, h), 4))
            return 1, s
        return (-z, 1) if z < 0 else (1, z)

    def prepare(self):
        if self.img is None:
            return
        k, s = self.factor()
        w, h, px = self.img
        dw, dh, buf = shrink(w, h, px, k)
        self.disp = (dw, dh, bytes(buf), s)

    def on_resize(self):
        if self.zoom == 0:
            self.prepare()

    def level(self):
        """Zoom efectivo como entero: N = ampliar xN, -N = reducir /N, 1 = 100 %."""
        k, s = self.factor()
        return s if s > 1 else (-k if k > 1 else 1)

    def set_level(self, z):
        self.zoom = max(-16, min(8, z))
        self.ox = self.oy = 0
        self.prepare()
        self.redraw()

    def zoom_in(self):
        c = self.level()
        self.set_level(c + 1 if c >= 1 else (1 if c == -2 else c + 1))

    def zoom_out(self):
        c = self.level()
        self.set_level(c - 1 if c > 1 else (-2 if c == 1 else c - 1))

    def fit(self):
        self.zoom = 0
        self.ox = self.oy = 0
        self.prepare()
        self.redraw()

    def siblings(self):
        if not self.path:
            return []
        d = self.path.rsplit("/", 1)[0] or "/"
        try:
            names = sorted(n for n, t in listdir(d) if t != "dir" and n.lower().endswith(IMG_EXT))
        except OSError:
            return []
        return [(d.rstrip("/") + "/" + n) for n in names]

    def step(self, d):
        sib = self.siblings()
        if not sib:
            return
        i = sib.index(self.path) if self.path in sib else -1
        self.load(sib[(i + d) % len(sib)])

    def prev(self):
        self.step(-1)

    def next(self):
        self.step(1)

    def open_dialog(self):
        def done(v):
            if v:
                self.load(v)
        self.wm.add(Prompt("Abrir imagen", "Ruta del BMP/PPM/PGM:", self.path or "/usr/share/images/", done))

    def edit(self):
        if self.path and self.img is not None:
            self.wm.add(Paint(self.path))

    def clamp(self):
        if self.disp is None:
            return
        dw, dh, buf, s = self.disp
        ax, ay, aw, ah = self.area()
        self.ox = max(0, min(max(0, dw * s - aw), self.ox))
        self.oy = max(0, min(max(0, dh * s - ah), self.oy))

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            self.oy += 60 * b
            self.clamp()
            self.redraw()
        elif kind == "down" and y >= 44:
            self.drag0 = (x, y, self.ox, self.oy)
        elif kind == "drag" and self.drag0 is not None:
            x0, y0, ox, oy = self.drag0
            self.ox, self.oy = ox - (x - x0), oy - (y - y0)
            self.clamp()
            self.redraw()
        elif kind == "up":
            self.drag0 = None
        elif kind == "double":
            if self.zoom:
                self.fit()
            else:
                self.set_level(1)

    def on_key(self, k):
        if k in ("right", " ", "pgdn"):
            self.next()
        elif k in ("left", "backspace", "pgup"):
            self.prev()
        elif k in ("+", "="):
            self.zoom_in()
        elif k == "-":
            self.zoom_out()
        elif k == "0":
            self.fit()
        elif k == "down":
            self.on_mouse("wheel", 0, 0, 1)
        elif k == "up":
            self.on_mouse("wheel", 0, 0, -1)

    def draw_content(self, g, x, y, w, h):
        ax, ay, aw, ah = self.area()
        g.append(("rect", x + ax, y + ay, aw, ah, 0x1F2937))
        info = ""
        if self.disp is not None:
            dw, dh, buf, s = self.disp
            iw, ih = dw * s, dh * s
            px = x + ax + max(0, (aw - iw) // 2) - (self.ox if iw > aw else 0)
            py = y + ay + max(0, (ah - ih) // 2) - (self.oy if ih > ah else 0)
            g.append(("clip_push", x + ax, y + ay, aw, ah))
            g.append(("image", px, py, dw, dh, buf, s))
            g.append(("clip_pop",))
            w0, h0, _ = self.img
            k, s2 = self.factor()
            pct = 100 * s2 // k
            info = "%s   %dx%d   %d%%" % (self.path, w0, h0, pct)
        elif self.err:
            g.append(("text", x + 20, y + ay + 20, clip_text("No se puede mostrar: " + self.err, w - 40),
                      0xFCA5A5, None))
            info = self.path or ""
        else:
            g.append(("text", x + 20, y + ay + 20, "Abre una imagen BMP, PPM o PGM.", 0xE5E7EB, None))
        g.append(("text", x + 8, y + h - 22, clip_text(info, w - 16), T["muted"], None))


# ================================================================== Calendario
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]


def civil_from_days(z):
    """Días desde 1970-01-01 -> (año, mes, día). Algoritmo de H. Hinnant (gregoriano proléptico)."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + 1 if m <= 2 else y), m, d


def days_from_civil(y, m, d):
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def today_days():
    try:
        off = int(SETTINGS.get("tz", "0"))
    except ValueError:
        off = 0
    return (int(time()) + off * 3600) // 86400


class Calendar(Window):
    icon = "calendar"
    resizable = False
    CW, CH = 38, 28

    def __init__(self):
        Window.__init__(self, "Calendario", 7 * self.CW + 20 + 2, 6 * self.CH + 112 + TITLE_H)
        y, m, d = civil_from_days(today_days())
        self.year, self.month = y, m
        self.add_button(10, 8, 34, 28, "<", self.prev)
        self.add_button(48, 8, 34, 28, ">", self.next)
        self.add_button(7 * self.CW + 10 - 60, 8, 60, 28, "Hoy", self.today)

    def prev(self):
        self.year, self.month = (self.year, self.month - 1) if self.month > 1 else (self.year - 1, 12)
        self.redraw()

    def next(self):
        self.year, self.month = (self.year, self.month + 1) if self.month < 12 else (self.year + 1, 1)
        self.redraw()

    def today(self):
        self.year, self.month, d = civil_from_days(today_days())
        self.redraw()

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            if b > 0:
                self.next()
            else:
                self.prev()

    def on_key(self, k):
        if k in ("left", "pgup"):
            self.prev()
        elif k in ("right", "pgdn"):
            self.next()
        elif k in ("home", "t"):
            self.today()
        elif k == "esc":
            self.close()

    def draw_content(self, g, x, y, w, h):
        title = "%s %d" % (MESES[self.month - 1], self.year)
        g.append(("text", x + 92, y + 13, title, T["text"], None))
        first = days_from_civil(self.year, self.month, 1)
        wd = (first + 3) % 7                       # 1970-01-01 fue jueves; lunes = 0
        nxt = days_from_civil(self.year + (self.month == 12), self.month % 12 + 1, 1)
        ndays = nxt - first
        today = today_days()
        gx, gy = x + 10, y + 48
        for i, dname in enumerate(DIAS):
            g.append(("text", gx + i * self.CW + 11, gy, dname, T["muted"] if i < 5 else T["accent"], None))
        for d in range(ndays):
            cell = wd + d
            cx = gx + (cell % 7) * self.CW
            cy = gy + 24 + (cell // 7) * self.CH
            if first + d == today:
                g.append(("rect", cx + 2, cy, self.CW - 4, self.CH - 4, T["accent"]))
                col = T["accent_text"]
            else:
                col = T["text"] if cell % 7 < 5 else T["muted"]
            s = str(d + 1)
            g.append(("text", cx + (self.CW - FW * len(s)) // 2, cy + 4, s, col, None))
        y0, m0, d0 = civil_from_days(today)
        g.append(("text", x + 10, y + h - 24, "Hoy: %s %d de %s de %d" % (
            ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][(today + 3) % 7],
            d0, MESES[m0 - 1], y0), T["muted"], None))


# ================================================================== Ayuda
HELP = [
    ("Escritorio", [
        ("Super / F1", "abre el menú PyOS (luego flechas, una letra salta a esa opción)"),
        ("Alt+Tab", "cambia de ventana"),
        ("Alt+W / F4", "cierra la ventana activa"),
        ("Arrastrar título", "al borde izq./der.: media pantalla; arriba: maximizar"),
        ("Doble clic título", "maximiza / restaura"),
        ("Clic derecho", "menú del escritorio, de la tarea (barra) o de la app"),
        ("Clic en el reloj", "calendario"),
    ]),
    ("Texto", [
        ("Ctrl+A / C / X / V", "seleccionar todo, copiar, cortar, pegar (Notas, campos)"),
        ("Ctrl+F / F3", "buscar / siguiente (Notas)"),
        ("Ctrl+S / Ctrl+O", "guardar / abrir (Notas, Paint)"),
        ("Terminal", "seleccionar copia, clic derecho pega, Ctrl+C interrumpe"),
    ]),
    ("Aplicaciones", [
        ("Archivos", "Supr borra, F2 renombra, Ctrl+C/X/V archivos, Ctrl+L ir a"),
        ("Navegador", "Ctrl+L dirección, Retroceso atrás, Esc cancela, F5 recarga"),
        ("Paint", "1-6 herramientas, Ctrl+Z deshace, rueda desplaza"),
        ("Imágenes", "flechas: anterior/siguiente, + / - / 0 zoom"),
        ("Buscaminas", "clic derecho bandera, doble clic en número despeja"),
    ]),
]


class Help(Window):
    icon = "info"
    min_w = 420
    min_h = 220

    def __init__(self):
        Window.__init__(self, "Ayuda de PyOS LOOK", 700, 520)
        self.top_i = 0
        self.rows = []
        for sec, items in HELP:
            self.rows.append(("h", sec, ""))
            for k, v in items:
                self.rows.append(("i", k, v))
            self.rows.append(("s", "", ""))

    def visible(self):
        cx, cy, cw, ch = self.content()
        return max(1, (ch - 16) // FH)

    def on_resize(self):
        """Parte las descripciones largas según el ancho de la ventana."""
        cx, cy, cw, ch = self.content()
        cols = max(10, (cw - 230 - 24) // FW)
        self.rows = []
        for sec, items in HELP:
            self.rows.append(("h", sec, ""))
            for k, v in items:
                words = v.split(" ")
                line = ""
                first = True
                for wd in words:
                    if line and len(line) + 1 + len(wd) > cols:
                        self.rows.append(("i", k if first else "", line))
                        first = False
                        line = wd
                    else:
                        line = (line + " " + wd) if line else wd
                self.rows.append(("i", k if first else "", line))
            self.rows.append(("s", "", ""))
        self.top_i = min(self.top_i, max(0, len(self.rows) - self.visible()))

    def draw_content(self, g, x, y, w, h):
        n = self.visible()
        for i in range(n):
            j = self.top_i + i
            if j >= len(self.rows):
                break
            kind, a, b = self.rows[j]
            yy = y + 8 + i * FH
            if kind == "h":
                g.append(("text", x + 12, yy, a, T["accent"], None))
                g.append(("text", x + 13, yy, a, T["accent"], None))
            elif kind == "i":
                g.append(("text", x + 24, yy, a, T["text"], None))
                g.append(("text", x + 230, yy, clip_text(b, w - 244), T["muted"], None))
        d_scrollbar(g, x + w - 12, y + 2, h - 4, len(self.rows), n, self.top_i)

    def scroll(self, d):
        self.top_i = max(0, min(max(0, len(self.rows) - self.visible()), self.top_i + d))
        self.redraw()

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            self.scroll(3 * b)

    def on_key(self, k):
        if k in ("down", "pgdn"):
            self.scroll(1 if k == "down" else self.visible())
        elif k in ("up", "pgup"):
            self.scroll(-1 if k == "up" else -self.visible())
        elif k == "esc":
            self.close()
