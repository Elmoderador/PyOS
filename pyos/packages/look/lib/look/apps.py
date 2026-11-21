# /lib/look/apps.py — aplicaciones de PyOS LOOK.
EAGAIN = 11


def run_capture(path, argv, cwd="/"):
    """Ejecuta un programa y devuelve (estado, salida). Bloquea LOOK mientras dura."""
    r, w = pipe()
    try:
        pid = spawn(path, argv, {1: w, 2: w}, cwd)
    except OSError as e:
        close(r)
        close(w)
        return 127, "no se pudo ejecutar %s: %s" % (path, e)
    close(w)
    out = []
    while True:
        d = read(r, 4096)
        if not d:
            break
        out.append(d)
    close(r)
    got, st = waitpid(pid)
    return st, b"".join(out).decode("utf-8", "replace")


def program_path(name):
    for d in ("/bin/", "/sbin/"):
        if exists(d + name + ".py"):
            return d + name + ".py"
    return None


def plural(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


FILE_CLIP = ["copy", []]              # portapapeles de archivos: (operación, rutas)


def copy_tree(src, dst):
    if stat(src).get("type") == "dir":
        mkdir(dst)
        for n, t in listdir(src):
            copy_tree(src.rstrip("/") + "/" + n, dst + "/" + n)
    else:
        write_file(dst, read_file(src))


def remove_tree(path):
    if stat(path).get("type") == "dir":
        for n, t in listdir(path):
            remove_tree(path.rstrip("/") + "/" + n)
        rmdir(path)
    else:
        unlink(path)


def tree_stats(path):
    """(número de elementos dentro, bytes) de una carpeta, recursivo."""
    n = size = 0
    try:
        items = listdir(path)
    except OSError:
        return 0, 0
    for name, t in items:
        p = path.rstrip("/") + "/" + name
        n += 1
        if t == "dir":
            a, b = tree_stats(p)
            n += a
            size += b
        else:
            try:
                size += stat(p).get("size", 0)
            except OSError:
                pass
    return n, size


# ================================================================== Terminal
class Terminal(Window):
    icon = "terminal"
    sel_a = None                      # selección con el ratón: (línea absoluta, columna)
    sel_b = None
    drawn = None                      # filas tal como se pintaron la última vez (repintado parcial)
    drawn_state = None
    drawn_cur = (0, 0)
    min_w = 330
    min_h = 200
    HIST = 400

    def __init__(self, argv=None, path=None, cwd="/root", title=None):
        self.argv = argv or ["sh"]
        self.path = path or program_path(self.argv[0]) or "/bin/sh.py"
        Window.__init__(self, title or ("Terminal" if self.argv[0] == "sh" else self.argv[0]),
                        FW * 84 + 2 + 14, FH * 24 + TITLE_H + 1 + 8)
        self.cwd = cwd
        self.cols = 80
        self.rows = 24
        self.grid = [[" "] * self.cols for _ in range(self.rows)]
        self.hist = []
        self.view = 0
        self.r = 0
        self.c = 0
        self.line = ""
        self.pid = None
        self.fd_in = None
        self.fd_out = None
        self.pend = b""
        self.state = 0
        self.params = ""
        self.dead = None
        self.dirty = False

    # ---------------------------------------------------------- proceso
    def start(self):
        rin_, win_ = pipe()
        rout, wout = pipe()
        ttyctl("winsize", (self.cols, self.rows))
        try:
            self.pid = spawn(self.path, self.argv, {0: rin_, 1: wout, 2: wout}, self.cwd)
        except OSError as e:
            self.feed(("no se pudo lanzar %s: %s\n" % (self.path, e)).encode())
            self.dead = 127
        ttyctl("winsize", None)
        close(rin_)
        close(wout)
        self.fd_in = win_
        self.fd_out = rout
        set_nonblock(rout)

    def on_resize(self):
        cx, cy, cw, ch = self.content()
        cols = max(20, (cw - 8 - 12) // FW)
        rows = max(5, (ch - 8) // FH)
        if (cols, rows) != (self.cols, self.rows):
            old = ["".join(r).rstrip() for r in self.grid]
            keep = old[max(0, len(old) - rows):] if self.r >= rows else old[:rows]
            if self.r >= rows:
                self.hist.extend(old[:len(old) - rows])
                self.r = rows - 1
            self.cols, self.rows = cols, rows
            self.grid = [list(l[:cols].ljust(cols)) for l in keep]
            while len(self.grid) < rows:
                self.grid.append([" "] * cols)
            self.c = min(self.c, cols - 1)
        if self.pid is None and self.dead is None:
            self.start()

    def on_close(self):
        if self.pid is not None and self.dead is None:
            for sig in (SIGTERM, SIGKILL):
                try:
                    kill(self.pid, sig)
                except OSError:
                    pass
        for fd in (self.fd_in, self.fd_out):
            if fd is not None:
                try:
                    close(fd)
                except OSError:
                    pass
        self.fd_in = self.fd_out = None
        if self.pid is not None and self.dead is None:
            reap_later(self.pid)               # aún muriendo: el WM lo recoge (sin zombis)
        return True

    def tick(self, now):
        got = 0
        if self.fd_out is not None:
            while got < 32768:
                try:
                    d = read(self.fd_out, 4096)
                except OSError as e:
                    if e.errno == EAGAIN:
                        break
                    d = b""
                if not d:
                    close(self.fd_out)
                    self.fd_out = None
                    break
                self.feed(d)
                got += len(d)
        if self.pid is not None and self.dead is None:
            try:
                p, st = waitpid(self.pid, True)
            except OSError:
                p, st = self.pid, 0
            if p == self.pid and self.fd_out is None:
                self.dead = st
                self.feed(("\n[proceso terminado: %s] Intro cierra la ventana\n" % status_text(st)).encode())
        if self.dirty:
            self.dirty = False
            self.smart_redraw()
        # solo "ocupado" si acaba de llegar salida: el kernel despierta a LOOK cuando el
        # programa escribe en la tubería, así que en reposo no hace falta sondear cada 40 ms
        return (self.fd_out is not None and got > 0) or \
            (self.fd_out is None and self.pid is not None and self.dead is None)

    def smart_redraw(self):
        """Solo se repintan las filas que han cambiado (en UEFI, teclear en una terminal llena
        de texto costaba repintar la ventana entera en cada pulsación)."""
        if self.wm is None or self.minimized:
            return
        rows = ["".join(r) for r in self.grid]
        state = (len(self.hist), self.view, self.sel_a, self.sel_b, self.dead, self.cols, self.rows)
        cur = (self.r, self.c)
        if self.drawn is None or state != self.drawn_state or len(rows) != len(self.drawn):
            self.redraw()
        else:
            cx, cy, cw, ch = self.content()
            changed = set(i for i in range(len(rows)) if rows[i] != self.drawn[i])
            if cur != self.drawn_cur:
                changed.add(cur[0])
                changed.add(self.drawn_cur[0])
            for i in changed:
                if 0 <= i < self.rows:
                    self.wm.damage((cx, cy + 4 + i * FH, cw - 14, FH))
        self.drawn = rows
        self.drawn_state = state
        self.drawn_cur = cur

    # ---------------------------------------------------------- emulación de terminal
    def newline(self):
        self.r += 1
        if self.r >= self.rows:
            self.hist.append("".join(self.grid.pop(0)).rstrip())
            if len(self.hist) > self.HIST:
                del self.hist[0]
            self.grid.append([" "] * self.cols)
            self.r = self.rows - 1

    def put(self, ch):
        if self.c >= self.cols:
            self.c = 0
            self.newline()
        self.grid[self.r][self.c] = ch
        self.c += 1

    def csi(self, p, f):
        nums = []
        for x in p.replace("?", "").split(";"):
            nums.append(int(x) if x.isdigit() else 0)
        a = nums[0] if nums else 0
        if f in "Hf":
            r = (nums[0] if nums and nums[0] else 1) - 1
            c = (nums[1] if len(nums) > 1 and nums[1] else 1) - 1
            self.r = min(max(r, 0), self.rows - 1)
            self.c = min(max(c, 0), self.cols - 1)
        elif f == "J":
            if a in (2, 3):
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
            elif a == 0:
                self.grid[self.r][self.c:] = [" "] * (self.cols - self.c)
                for r in range(self.r + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
        elif f == "K":
            self.grid[self.r][self.c:] = [" "] * (self.cols - self.c)
        elif f == "A":
            self.r = max(0, self.r - max(1, a))
        elif f == "B":
            self.r = min(self.rows - 1, self.r + max(1, a))
        elif f == "C":
            self.c = min(self.cols - 1, self.c + max(1, a))
        elif f == "D":
            self.c = max(0, self.c - max(1, a))

    def feed(self, data):
        data = self.pend + data
        self.pend = b""
        cut = len(data)
        while cut > 0 and cut > len(data) - 4 and data[cut - 1] >= 0x80:
            b = data[cut - 1]
            if b >= 0xC0:
                need = 2 if b < 0xE0 else (3 if b < 0xF0 else 4)
                if len(data) - (cut - 1) < need:
                    self.pend = data[cut - 1:]
                    data = data[:cut - 1]
                break
            cut -= 1
        for ch in data.decode("utf-8", "replace"):
            st = self.state
            if st == 0:
                if ch == "\x1b":
                    self.state = 1
                elif ch == "\n":
                    self.c = 0
                    self.newline()
                elif ch == "\r":
                    self.c = 0
                elif ch == "\b":
                    self.c = max(0, self.c - 1)
                elif ch == "\t":
                    for _ in range(8 - self.c % 8):
                        self.put(" ")
                elif ch >= " ":
                    self.put(ch)
            elif st == 1:
                if ch == "[":
                    self.state = 2
                    self.params = ""
                else:
                    self.state = 0
            else:
                if "@" <= ch <= "~":
                    self.csi(self.params, ch)
                    self.state = 0
                else:
                    self.params += ch
                    if len(self.params) > 32:
                        self.state = 0
        self.view = 0
        self.dirty = True
        self.sel_a = self.sel_b = None

    # ---------------------------------------------------------- selección (estilo X11)
    def all_lines(self):
        return self.hist + ["".join(r) for r in self.grid]

    def pos_at(self, x, y):
        lines_n = len(self.hist) + self.rows
        first = lines_n - self.rows - self.view
        j = min(lines_n - 1, max(0, first + (y - 4) // FH))
        return (j, max(0, min(self.cols, (x - 4 + FW // 2) // FW)))

    def selection(self):
        if self.sel_a is None or self.sel_a == self.sel_b:
            return None
        a, b = self.sel_a, self.sel_b
        return (a, b) if a < b else (b, a)

    def sel_text(self):
        s = self.selection()
        if s is None:
            return ""
        lines = self.all_lines()
        (r0, c0), (r1, c1) = s
        out = []
        for j in range(r0, r1 + 1):
            l = lines[j]
            out.append(l[c0 if j == r0 else 0:c1 if j == r1 else len(l)].rstrip())
        return "\n".join(out)

    def interrupt(self):
        """Ctrl+C sin selección: SIGINT a los programas en primer plano lanzados por el
        shell de ESTA terminal (la consola es una sola; cada terminal de LOOK filtra los suyos)."""
        self.feed(b"^C")
        if self.pid is None or self.dead is not None:
            return
        try:
            fg = ttyctl("fg")
        except OSError:
            fg = []
        hit = False
        for pid in fg:
            try:
                st = read_file("/proc/%d/status" % pid).decode()
            except OSError:
                continue
            if proc_field(st, "PPid") == str(self.pid):
                try:
                    kill(pid, SIGINT)
                    hit = True
                except OSError:
                    pass
        if not hit:
            # nada en marcha: como un shell, se descarta la línea a medio escribir
            self.feed(b"\n")
            self.line = ""
            self.send("\n")

    def paste(self, text):
        for ch in text:
            if ch == "\n":
                self.on_key("enter")
            elif ch == "\t":
                self.on_key("tab")
            elif printable(ch):
                self.on_key(ch)

    # ---------------------------------------------------------- dibujo y teclado
    def draw_content(self, g, x, y, w, h):
        g.append(("rect", x, y, w, h, T["term_bg"]))
        lines = self.hist + ["".join(r) for r in self.grid]
        first = len(lines) - self.rows - self.view
        sel = self.selection()
        for i in range(self.rows):
            j = first + i
            if sel is not None and sel[0][0] <= j <= sel[1][0]:
                a = sel[0][1] if j == sel[0][0] else 0
                b = sel[1][1] if j == sel[1][0] else self.cols
                if b > a:
                    g.append(("rect", x + 4 + a * FW, y + 4 + i * FH, (b - a) * FW, FH, 0x334155))
            if 0 <= j < len(lines) and lines[j].strip():
                g.append(("text", x + 4, y + 4 + i * FH, lines[j], T["term_fg"], None))
        if self.view == 0 and self is self.wm.top() and self.dead is None:
            cx = x + 4 + self.c * FW
            cy = y + 4 + self.r * FH
            g.append(("rect", cx, cy + FH - 4, FW, 3, T["term_fg"]))
        d_scrollbar(g, x + w - 12, y + 2, h - 4, len(lines), self.rows, max(0, first))

    def send(self, s):
        if self.fd_in is None:
            return
        try:
            write(self.fd_in, s.encode("utf-8"))
        except OSError:
            pass

    def on_key(self, k):
        if self.dead is not None:
            if k == "enter":
                self.close()
            return
        if k == "enter":
            self.feed(b"\n")
            self.send(self.line + "\n")
            self.line = ""
        elif k == "backspace":
            if self.line:
                self.line = self.line[:-1]
                self.feed(b"\b \b")
        elif k == "ctrl-d":
            if self.fd_in is not None:
                close(self.fd_in)
                self.fd_in = None
        elif k == "ctrl-u":
            self.feed(b"\b \b" * len(self.line))
            self.line = ""
        elif k == "ctrl-l":
            self.feed(b"\x1b[2J\x1b[H")
        elif k == "pgup":
            self.view = min(len(self.hist), self.view + self.rows // 2)
            self.redraw()
        elif k == "pgdn":
            self.view = max(0, self.view - self.rows // 2)
            self.redraw()
        elif k == "tab":
            self.line += "    "
            self.feed(b"    ")
        elif k == "ctrl-v":
            self.paste(clip_get())
        elif k == "ctrl-c":
            if self.selection() is not None:
                clip_set(self.sel_text())
                self.sel_a = self.sel_b = None
                self.redraw()
            else:
                self.interrupt()
        elif printable(k):
            self.line += k
            self.feed(k.encode("utf-8"))

    def on_mouse(self, kind, x, y, b):
        cx, cy, cw, ch = self.content()
        if x < cw - 14:
            if kind == "down":
                self.sel_a = self.sel_b = self.pos_at(x, y)
                self.redraw()
                return
            if kind == "drag" and self.sel_a is not None:
                self.sel_b = self.pos_at(x, y)
                self.redraw()
                return
            if kind == "up" and self.sel_a is not None:
                t = self.sel_text()
                if t:
                    clip_set(t)               # seleccionar copia (como en X11)
                return
            if kind == "right":
                self.paste(clip_get())        # clic derecho pega
                return
        if kind == "wheel":
            self.view = min(len(self.hist), max(0, self.view - 3 * b))
            self.redraw()
            return
        cx, cy, cw, ch = self.content()
        if kind in ("down", "drag") and x >= cw - 14:
            total = len(self.hist) + self.rows
            first = (y * total) // max(1, ch) - self.rows // 2
            self.view = min(len(self.hist), max(0, len(self.hist) - first))
            self.redraw()


# ================================================================== Archivos
class Files(Window):
    icon = "folder"
    min_w = 600
    min_h = 300
    ROW = 22

    def __init__(self, path="/root"):
        Window.__init__(self, "Archivos", 660, 460)
        self.path = path
        self.entries = []
        self.sel = 0
        self.top_i = 0
        self.status = ""
        x = 8
        for label, fn, w in (("Subir", self.go_up, 70), ("Abrir", self.open_sel, 70),
                             ("Nueva carpeta", self.new_dir, 120), ("Renombrar", self.rename, 96),
                             ("Borrar", self.delete, 76), ("Terminal aquí", self.term_here, 120)):
            self.add_button(x, 8, w, 28, label, fn, label == "Abrir")
            x += w + 6
        self.load()

    def load(self):
        try:
            items = listdir(self.path)
            self.status = ""
        except OSError as e:
            items = []
            self.status = "no se puede leer: %s" % e
        dirs = sorted(n for n, t in items if t == "dir")
        files = sorted(n for n, t in items if t != "dir")
        self.entries = []
        for n in dirs:
            self.entries.append((n, "dir", 0))
        for n in files:
            try:
                size = stat(self.full(n)).get("size", 0)
            except OSError:
                size = 0
            self.entries.append((n, "file", size))
        self.sel = min(self.sel, max(0, len(self.entries) - 1))
        self.top_i = 0
        self.title = "Archivos - " + self.path
        self.redraw()
        if self.wm is not None:
            self.wm.damage(self.wm.taskbar_rect())

    def full(self, name):
        return (self.path.rstrip("/") + "/" + name) if self.path != "/" else "/" + name

    def visible(self):
        cx, cy, cw, ch = self.content()
        return max(1, (ch - 84 - 26) // self.ROW)

    def draw_content(self, g, x, y, w, h):
        d_field(g, x + 8, y + 44, w - 16, 26, self.path, False)
        lx, ly = x + 8, y + 78
        lw, lh = w - 16, h - 78 - 30
        g.append(("rect", lx, ly, lw, lh, T["field"]))
        g.append(("frame", lx, ly, lw, lh, T["line"], 1))
        n = self.visible()
        if self.sel < self.top_i:
            self.top_i = self.sel
        if self.sel >= self.top_i + n:
            self.top_i = self.sel - n + 1
        self.top_i = max(0, min(self.top_i, max(0, len(self.entries) - n)))
        for i in range(n):
            j = self.top_i + i
            if j >= len(self.entries):
                break
            name, typ, size = self.entries[j]
            ry = ly + 2 + i * self.ROW
            sel = j == self.sel
            if sel:
                g.append(("rect", lx + 2, ry, lw - 16, self.ROW, T["sel"]))
            ic = ICONS["folder" if typ == "dir" else "file"]
            g.append(("bitmap", lx + 6, ry + 3, ic[0], ic[1], 1))
            col = T["sel_text"] if sel else T["text"]
            g.append(("text", lx + 28, ry + 2, clip_text(name, lw - 200), col, None))
            if typ != "dir":
                s = fmt_size(size)
                g.append(("text", lx + lw - 30 - FW * len(s), ry + 2, s, T["muted"], None))
        if not self.entries:
            msg = "Carpeta vacía" if not self.status else ""
            g.append(("text", lx + (lw - FW * len(msg)) // 2, ly + 40, msg, T["muted"], None))
        d_scrollbar(g, lx + lw - 12, ly + 2, lh - 4, len(self.entries), n, self.top_i)
        info = self.status or plural(len(self.entries), "elemento", "elementos")
        g.append(("text", x + 8, y + h - 24, clip_text(info, w - 16), T["muted"], None))

    def row_at(self, x, y):
        if y < 80:
            return -1
        j = self.top_i + (y - 80) // self.ROW
        return j if 0 <= j < len(self.entries) else -1

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            if self.entries:
                self.sel = max(0, min(len(self.entries) - 1, max(0, self.sel + 3 * b)))
                self.redraw()
            return
        j = self.row_at(x, y)
        if kind == "down" and 44 <= y < 70:
            self.ask_go()
            return
        if kind == "right":
            if j >= 0:
                self.sel = j
                self.redraw()
            cx, cy, cw, ch = self.content()
            self.wm.popup(self.context_items(j >= 0), cx + x, cy + y)
            return
        if kind == "down" and j >= 0:
            self.sel = j
            self.redraw()
        elif kind == "double" and j >= 0:
            self.sel = j
            self.open_sel()

    def on_key(self, k):
        if k == "down":
            self.sel = max(0, min(len(self.entries) - 1, self.sel + 1))
        elif k == "up":
            self.sel = max(0, self.sel - 1)
        elif k == "pgdn":
            self.sel = max(0, min(len(self.entries) - 1, self.sel + self.visible()))
        elif k == "pgup":
            self.sel = max(0, self.sel - self.visible())
        elif k == "enter":
            self.open_sel()
            return
        elif k == "backspace":
            self.go_up()
            return
        elif k == "delete":
            self.delete()
            return
        elif k == "f2":
            self.rename()
            return
        elif k == "ctrl-c":
            self.clip("copy")
            return
        elif k == "ctrl-x":
            self.clip("cut")
            return
        elif k == "ctrl-v":
            self.paste()
            return
        elif k == "ctrl-l":
            self.ask_go()
            return
        elif k == "f5":
            self.load()
            return
        else:
            return
        self.redraw()

    def current(self):
        if 0 <= self.sel < len(self.entries):
            return self.entries[self.sel]
        return None

    def go_up(self):
        if self.path != "/":
            self.path = self.path.rstrip("/").rsplit("/", 1)[0] or "/"
            self.sel = 0
            self.load()

    def open_sel(self):
        e = self.current()
        if e is None:
            return
        name, typ, size = e
        p = self.full(name)
        if typ == "dir":
            self.path = p
            self.sel = 0
            self.load()
        elif name.endswith(".py") and (self.path in ("/bin", "/sbin")):
            self.wm.add(Terminal([name[:-3]], p, "/root"))
        elif name.endswith(".py"):
            self.wm.add(Notes(p))
        elif name.lower().endswith((".html", ".htm")):
            self.wm.add(Browser("file://" + p))
        elif name.lower().endswith((".bmp", ".ppm", ".pgm")):
            self.wm.add(ImageViewer(p))
        else:
            self.wm.add(Notes(p))

    def new_dir(self):
        def done(v):
            if v:
                try:
                    mkdir(self.full(v))
                except OSError as e:
                    self.wm.message("Archivos", "No se pudo crear la carpeta:\n%s" % e)
                self.load()
        self.wm.add(Prompt("Nueva carpeta", "Nombre de la carpeta:", "", done))

    def rename(self):
        e = self.current()
        if e is None:
            return

        def done(v):
            if v and v != e[0]:
                try:
                    rename(self.full(e[0]), self.full(v))
                except OSError as err:
                    self.wm.message("Archivos", "No se pudo renombrar:\n%s" % err)
                self.load()
        self.wm.add(Prompt("Renombrar", "Nuevo nombre para %s:" % e[0], e[0], done))

    def delete(self):
        e = self.current()
        if e is None:
            return

        path = self.full(e[0])

        def really():
            try:
                remove_tree(path)
            except OSError as err:
                self.wm.message("Archivos", "No se pudo borrar:\n%s" % err)
            self.load()
        if e[1] == "dir":
            n, size = tree_stats(path)
            q = "¿Borrar la carpeta \"%s\"%s?" % (e[0], " y todo su contenido (%s, %s)" % (
                plural(n, "elemento", "elementos"), fmt_size(size)) if n else "")
        else:
            q = "¿Borrar el archivo \"%s\"?" % e[0]
        big = e[1] == "dir" and tree_stats(path)[0] > 0
        self.wm.message("Borrar", q, [("Borrar", really), ("Cancelar", None)], 1 if big else 0)

    # ---------------------------------------------------------- copiar / cortar / pegar
    def clip(self, op):
        e = self.current()
        if e is None:
            return
        FILE_CLIP[0] = op
        FILE_CLIP[1] = [self.full(e[0])]
        self.status = "%s: %s (Ctrl+V para pegar)" % ("copiado" if op == "copy" else "cortado", e[0])
        self.redraw()

    def paste(self):
        op, srcs = FILE_CLIP
        if not srcs:
            self.status = "el portapapeles de archivos está vacío"
            self.redraw()
            return
        done = 0
        for src in srcs:
            name = src.rstrip("/").rsplit("/", 1)[-1]
            dst = self.full(name)
            if dst == src and op == "cut":
                continue
            if self.path == src or self.path.startswith(src.rstrip("/") + "/"):
                self.wm.message("Archivos", "No se puede pegar una carpeta dentro de sí misma.")
                return
            base, ext = (name.rsplit(".", 1)[0], "." + name.rsplit(".", 1)[1]) if "." in name[1:] else (name, "")
            k = 1
            while exists(dst):
                k += 1
                dst = self.full("%s (%d)%s" % (base, k, ext))
            try:
                if op == "cut":
                    rename(src, dst)
                else:
                    copy_tree(src, dst)
                done += 1
            except OSError as err:
                self.wm.message("Archivos", "No se pudo pegar %s:\n%s" % (name, err))
        if op == "cut":
            FILE_CLIP[1] = []
        self.load()
        self.status = "pegado: %s" % plural(done, "elemento", "elementos")
        if done:
            self.wm.toast("Archivos: %s %s\nen %s" % (plural(done, "elemento", "elementos"),
                                                       ("movido" if op == "cut" else "copiado") + ("s" if done > 1 else ""),
                                                       self.path))
        self.redraw()

    def ask_go(self):
        def done(v):
            if v:
                v = v if v.startswith("/") else self.full(v)
                try:
                    stat(v)
                except OSError as err:
                    self.wm.message("Archivos", "No existe %s:\n%s" % (v, err))
                    return
                if v != "/":
                    v = v.rstrip("/")
                self.path = v
                self.sel = 0
                self.load()
        self.wm.add(Prompt("Ir a", "Carpeta:", self.path, done))

    def properties(self):
        e = self.current()
        if e is None:
            return
        p = self.full(e[0])
        if e[1] == "dir":
            n, size = tree_stats(p)
            info = "Carpeta: %s\nContiene: %s (%s)" % (p, plural(n, "elemento", "elementos"), fmt_size(size))
        else:
            info = "Archivo: %s\nTamaño: %s (%d bytes)" % (p, fmt_size(e[2]), e[2])
        self.wm.message("Propiedades", info)

    def open_with(self, cls, prefix=""):
        def f():
            e = self.current()
            if e is not None:
                self.wm.add(cls(prefix + self.full(e[0])))
        return f

    def context_items(self, on_item):
        paste = ("Pegar", "file", self.paste) if FILE_CLIP[1] else None
        if not on_item:
            items = [("Nueva carpeta", "folder", self.new_dir), ("Terminal aquí", "terminal", self.term_here),
                     ("Actualizar", "file", self.load)]
            return items + ([None, paste] if paste else [])
        e = self.current()
        items = [("Abrir", "folder" if e[1] == "dir" else "file", self.open_sel)]
        if e[1] != "dir":
            items += [("Abrir con Notas", "notes", self.open_with(Notes)),
                      ("Abrir con Navegador", "web", self.open_with(Browser, "file://"))]
            if e[0].lower().endswith(IMG_EXT):
                items += [("Abrir con Imágenes", "image", self.open_with(ImageViewer)),
                          ("Editar en Paint", "paint", self.open_with(Paint))]
        items += [None, ("Copiar", "file", lambda: self.clip("copy")), ("Cortar", "file", lambda: self.clip("cut"))]
        if paste:
            items.append(paste)
        items += [None, ("Renombrar", "notes", self.rename), ("Borrar", "power", self.delete),
                  ("Propiedades", "info", self.properties)]
        return items

    def term_here(self):
        self.wm.add(Terminal(cwd=self.path))


# ================================================================== Notas
class Notes(Window):
    icon = "notes"
    batching = False
    want_redraw = False
    min_w = 390
    min_h = 220

    def __init__(self, path=None):
        Window.__init__(self, "Notas", 640, 460)
        self.path = path
        self.lines = [""]
        self.r = 0
        self.c = 0
        self.top_i = 0
        self.left = 0
        self.modified = False
        self.status = ""
        self.anchor = None            # inicio de la selección (fila, col); el cursor es el otro extremo
        self.find_text = ""
        self.add_button(8, 8, 70, 28, "Nuevo", self.new)
        self.add_button(84, 8, 70, 28, "Abrir", self.ask_open)
        self.add_button(160, 8, 80, 28, "Guardar", self.save, True)
        self.add_button(246, 8, 120, 28, "Guardar como", self.save_as)
        if path:
            self.load(path)
        self.update_title()

    def update_title(self):
        self.title = "Notas - %s%s" % (self.path or "sin título", " *" if self.modified else "")
        if self.wm is not None:
            self.wm.damage(self.wm.taskbar_rect())

    def load(self, path):
        try:
            data = read_file(path)
        except OSError as e:
            self.status = "no se pudo abrir: %s" % e
            return
        if b"\x00" in data[:4096]:
            self.lines = ["(archivo binario: %d bytes, no se muestra)" % len(data)]
            self.path = None
        else:
            self.lines = data.decode("utf-8", "replace").replace("\t", "    ").split("\n")
            self.path = path
        self.r = self.c = self.top_i = 0
        self.anchor = None
        self.modified = False
        self.status = "%d líneas" % len(self.lines)
        self.update_title()
        self.redraw()

    def new(self):
        self.anchor = None
        self.lines = [""]
        self.path = None
        self.r = self.c = self.top_i = 0
        self.modified = False
        self.update_title()
        self.redraw()

    def ask_open(self):
        self.wm.add(Prompt("Abrir", "Ruta del archivo:", self.path or "/root/", self.load))

    def save(self):
        if not self.path:
            self.save_as()
            return
        try:
            write_file(self.path, "\n".join(self.lines))
            sync()
            self.modified = False
            self.status = "guardado: %s" % self.path
        except OSError as e:
            self.status = "error al guardar: %s" % e
        self.update_title()
        self.redraw()

    def save_as(self, then=None):
        def done(v):
            if v:
                self.path = v
                self.save()
                if then is not None and not self.modified:
                    then()
        self.wm.add(Prompt("Guardar como", "Guardar en:", self.path or "/root/nota.txt", done))

    closing_ok = False

    def unsaved(self):
        return self.modified

    def on_close(self):
        if not self.modified or self.closing_ok:
            return True

        def force():
            self.closing_ok = True
            self.close()

        def save_close():
            if self.path:
                self.save()
                if not self.modified:
                    force()
            else:
                self.save_as(force)
        self.wm.message("Notas", "¿Guardar los cambios de %s?" % (self.path or "la nota sin título"),
                        [("Guardar", save_close), ("No guardar", force), ("Cancelar", None)])
        return False

    def area(self):
        cx, cy, cw, ch = self.content()
        return (8, 44, cw - 16, ch - 44 - 30)

    def ensure_visible(self):
        ax, ay, aw, ah = self.area()
        rows = max(1, (ah - 8) // FH)
        cols = max(1, (aw - 50) // FW)
        if self.r < self.top_i:
            self.top_i = self.r
        if self.r >= self.top_i + rows:
            self.top_i = self.r - rows + 1
        if self.c < self.left:
            self.left = self.c
        if self.c >= self.left + cols:
            self.left = self.c - cols + 1
        return rows, cols

    def redraw(self):
        if self.batching:
            self.want_redraw = True
        else:
            Window.redraw(self)

    def on_key(self, k):
        """Envuelve key(): si solo cambian la línea del cursor (y la anterior), se repintan esas
        filas y la barra de estado, no la ventana entera."""
        st0 = (self.top_i, self.left, len(self.lines), self.anchor, self.modified, self.path)
        r0 = self.r
        self.batching = True
        self.want_redraw = False
        try:
            self.key(k)
        finally:
            self.batching = False
        if not self.want_redraw or self.wm is None:
            return
        self.ensure_visible()
        st1 = (self.top_i, self.left, len(self.lines), self.anchor, self.modified, self.path)
        if st0 != st1 or self.minimized:
            Window.redraw(self)
            return
        cx, cy, cw, ch = self.content()
        ax, ay, aw, ah = self.area()
        for j in set((r0, self.r)):
            self.wm.damage((cx + ax, cy + ay + 4 + (j - self.top_i) * FH, aw - 14, FH))
        self.wm.damage((cx, cy + ch - 30, cw, 30))

    def draw_content(self, g, x, y, w, h):
        ax, ay, aw, ah = self.area()
        g.append(("rect", x + ax, y + ay, aw, ah, T["field"]))
        g.append(("frame", x + ax, y + ay, aw, ah, T["line"], 1))
        rows, cols = self.ensure_visible()
        sel = self.sel_range()
        for i in range(rows):
            j = self.top_i + i
            if j >= len(self.lines):
                break
            yy = y + ay + 4 + i * FH
            g.append(("text", x + ax + 4, yy, "%3d" % (j + 1), T["muted"], None))
            if sel is not None and sel[0][0] <= j <= sel[1][0]:
                a = sel[0][1] if j == sel[0][0] else 0
                b = sel[1][1] if j == sel[1][0] else len(self.lines[j]) + 1
                a, b = max(a, self.left), min(b, self.left + cols)
                if b > a:
                    g.append(("rect", x + ax + 40 + (a - self.left) * FW, yy, (b - a) * FW, FH, T["sel"]))
            seg = self.lines[j][self.left:self.left + cols]
            if seg:
                g.append(("text", x + ax + 40, yy, seg, T["text"], None))
        if self is self.wm.top():
            cx = x + ax + 40 + (self.c - self.left) * FW
            cy = y + ay + 4 + (self.r - self.top_i) * FH
            g.append(("rect", cx, cy, 2, FH, T["accent"]))
        d_scrollbar(g, x + ax + aw - 12, y + ay + 2, ah - 4, len(self.lines), rows, self.top_i)
        st = self.status or "Ctrl+S guarda"
        g.append(("text", x + 8, y + h - 24, clip_text("Lín %d, col %d   %s" % (self.r + 1, self.c + 1, st), w - 16),
                  T["muted"], None))

    def changed(self):
        if not self.modified:
            self.modified = True
            self.update_title()

    # ---------------------------------------------------------- selección y portapapeles
    def sel_range(self):
        if self.anchor is None or self.anchor == (self.r, self.c):
            return None
        a, b = self.anchor, (self.r, self.c)
        return (a, b) if a < b else (b, a)

    def sel_text(self):
        s = self.sel_range()
        if s is None:
            return ""
        (r0, c0), (r1, c1) = s
        if r0 == r1:
            return self.lines[r0][c0:c1]
        out = [self.lines[r0][c0:]] + self.lines[r0 + 1:r1] + [self.lines[r1][:c1]]
        return "\n".join(out)

    def del_sel(self):
        s = self.sel_range()
        self.anchor = None
        if s is None:
            return False
        (r0, c0), (r1, c1) = s
        L = self.lines
        L[r0] = L[r0][:c0] + L[r1][c1:]
        del L[r0 + 1:r1 + 1]
        self.r, self.c = r0, c0
        self.changed()
        return True

    def insert(self, text):
        self.del_sel()
        L = self.lines
        parts = text.replace("\t", "    ").split("\n")
        tail = L[self.r][self.c:]
        L[self.r] = L[self.r][:self.c] + parts[0]
        for p in parts[1:]:
            self.r += 1
            L.insert(self.r, p)
        self.c = len(L[self.r])
        L[self.r] += tail
        self.changed()

    def find_next(self):
        """Busca desde el cursor hacia delante y da la vuelta al final del texto."""
        t = self.find_text
        if not t:
            return
        L = self.lines
        n = len(L)
        for k in range(n + 1):
            j = (self.r + k) % n
            p = L[j].find(t, self.c if k == 0 else 0)
            if k == n and p >= self.c:
                p = -1                             # vuelta completa: ya estaba mirado
            if p >= 0:
                self.anchor = (j, p)
                self.r, self.c = j, p + len(t)
                self.status = "encontrado en la línea %d" % (j + 1)
                self.redraw()
                return
        self.status = "no se encuentra: %s" % t
        self.redraw()

    def ask_find(self):
        def done(v):
            if v:
                self.find_text = v
                self.find_next()
        self.wm.add(Prompt("Buscar", "Texto a buscar (F3 repite):", self.find_text, done))

    def key(self, k):
        L = self.lines
        if k == "ctrl-s":
            self.save()
            return
        if k == "ctrl-o":
            self.ask_open()
            return
        if k == "ctrl-f":
            self.ask_find()
            return
        if k == "f3":
            self.find_next()
            return
        if k == "ctrl-a":
            self.anchor = (0, 0)
            self.r, self.c = len(L) - 1, len(L[-1])
            self.redraw()
            return
        if k in ("ctrl-c", "ctrl-x"):
            t = self.sel_text()
            if t:
                clip_set(t)
                self.status = "copiado (%d caracteres)" % len(t)
                if k == "ctrl-x":
                    self.del_sel()
                self.redraw()
            return
        if k == "ctrl-v":
            if clip_get():
                self.insert(clip_get())
                self.redraw()
            return
        if self.anchor is not None:
            if k in ("backspace", "delete"):
                if self.del_sel():
                    self.redraw()
                    return
            elif k == "enter" or k == "tab" or printable(k):
                self.del_sel()
            else:
                self.anchor = None             # moverse deshace la selección
        if k == "left":
            if self.c > 0:
                self.c -= 1
            elif self.r > 0:
                self.r -= 1
                self.c = len(L[self.r])
        elif k == "right":
            if self.c < len(L[self.r]):
                self.c += 1
            elif self.r < len(L) - 1:
                self.r += 1
                self.c = 0
        elif k == "up":
            self.r = max(0, self.r - 1)
            self.c = min(self.c, len(L[self.r]))
        elif k == "down":
            self.r = min(len(L) - 1, self.r + 1)
            self.c = min(self.c, len(L[self.r]))
        elif k == "home":
            self.c = 0
        elif k == "end":
            self.c = len(L[self.r])
        elif k == "pgup":
            self.r = max(0, self.r - 15)
            self.c = min(self.c, len(L[self.r]))
        elif k == "pgdn":
            self.r = min(len(L) - 1, self.r + 15)
            self.c = min(self.c, len(L[self.r]))
        elif k == "enter":
            line = L[self.r]
            indent = len(line) - len(line.lstrip(" "))
            L[self.r] = line[:self.c]
            L.insert(self.r + 1, " " * indent + line[self.c:])
            self.r += 1
            self.c = indent
            self.changed()
        elif k == "backspace":
            if self.c > 0:
                L[self.r] = L[self.r][:self.c - 1] + L[self.r][self.c:]
                self.c -= 1
            elif self.r > 0:
                self.c = len(L[self.r - 1])
                L[self.r - 1] += L.pop(self.r)
                self.r -= 1
            self.changed()
        elif k == "delete":
            if self.c < len(L[self.r]):
                L[self.r] = L[self.r][:self.c] + L[self.r][self.c + 1:]
            elif self.r < len(L) - 1:
                L[self.r] += L.pop(self.r + 1)
            self.changed()
        elif k == "tab":
            L[self.r] = L[self.r][:self.c] + "    " + L[self.r][self.c:]
            self.c += 4
            self.changed()
        elif printable(k):
            L[self.r] = L[self.r][:self.c] + k + L[self.r][self.c:]
            self.c += 1
            self.changed()
        else:
            return
        self.redraw()

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            self.r = max(0, min(len(self.lines) - 1, max(0, self.r + 3 * b)))
            self.c = min(self.c, len(self.lines[self.r]))
            self.redraw()
            return
        ax, ay, aw, ah = self.area()
        inside = ax <= x < ax + aw and ay <= y < ay + ah
        if kind in ("down", "drag") and (inside or kind == "drag"):
            self.r = max(0, min(len(self.lines) - 1, max(0, self.top_i + (y - ay - 4) // FH)))
            self.c = min(len(self.lines[self.r]), self.left + max(0, (x - ax - 40) // FW))
            if kind == "down":
                self.anchor = (self.r, self.c)
            self.redraw()
        elif kind == "double" and inside:
            line = self.lines[self.r]          # doble clic: selecciona la palabra
            a = b = min(self.c, len(line))
            while a > 0 and (line[a - 1].isalnum() or line[a - 1] == "_"):
                a -= 1
            while b < len(line) and (line[b].isalnum() or line[b] == "_"):
                b += 1
            self.anchor = (self.r, a)
            self.c = b
            self.redraw()
        elif kind == "right" and inside and clip_get():
            self.insert(clip_get())
            self.redraw()


# ================================================================== Procesos
def proc_field(text, key):
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return "?"


class Procs(Window):
    icon = "procs"
    min_w = 420
    min_h = 240
    ROW = 21

    def __init__(self):
        Window.__init__(self, "Procesos", 700, 470)
        self.rows = []
        self.sel = 0
        self.mem = ""
        self.next = 0
        self.add_button(8, 8, 96, 28, "Actualizar", self.refresh)
        self.add_button(110, 8, 96, 28, "Terminar", self.term, True)
        self.add_button(212, 8, 96, 28, "Matar", self.kill9)
        self.refresh()

    def refresh(self):
        rows = []
        for name, t in listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                st = read_file("/proc/" + name + "/status").decode()
                cmd = read_file("/proc/" + name + "/cmdline").decode().strip()
            except OSError:
                continue
            rows.append((int(name), proc_field(st, "PPid"), proc_field(st, "State"),
                         proc_field(st, "CpuTicks"), proc_field(st, "VmRSS"), cmd))
        rows.sort()
        self.rows = rows
        self.sel = min(self.sel, max(0, len(rows) - 1))
        try:
            m = read_file("/proc/meminfo").decode().splitlines()
            self.mem = "   ".join(l.replace("  ", " ") for l in m[:3])
        except OSError:
            self.mem = ""
        self.next = uptime_ms() + 2000
        self.redraw()

    def tick(self, now):
        if now >= self.next and not self.minimized:
            self.refresh()
        return False

    def draw_content(self, g, x, y, w, h):
        lx, ly, lw, lh = x + 8, y + 44, w - 16, h - 44 - 30
        g.append(("rect", lx, ly, lw, lh, T["field"]))
        g.append(("frame", lx, ly, lw, lh, T["line"], 1))
        hdr = "%5s %5s  %-9s %7s %10s  %s" % ("PID", "PPID", "ESTADO", "TICKS", "MEMORIA", "ORDEN")
        g.append(("rect", lx + 1, ly + 1, lw - 2, self.ROW, T["btn"]))
        g.append(("text", lx + 6, ly + 2, clip_text(hdr, lw - 12), T["text"], None))
        n = max(1, (lh - self.ROW - 4) // self.ROW)
        for i, row in enumerate(self.rows[:n]):
            ry = ly + 2 + self.ROW * (i + 1)
            sel = i == self.sel
            if sel:
                g.append(("rect", lx + 2, ry, lw - 4, self.ROW, T["sel"]))
            s = "%5d %5s  %-9s %7s %10s  %s" % row
            g.append(("text", lx + 6, ry + 1, clip_text(s, lw - 12), T["sel_text"] if sel else T["text"], None))
        g.append(("text", x + 8, y + h - 24, clip_text("%d procesos   %s" % (len(self.rows), self.mem), w - 16),
                  T["muted"], None))

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            if self.rows:
                self.sel = max(0, min(len(self.rows) - 1, max(0, self.sel + b)))
                self.redraw()
            return
        if kind == "down" and y >= 44 + 2 + self.ROW:
            j = (y - 46) // self.ROW - 1
            if 0 <= j < len(self.rows):
                self.sel = j
                self.redraw()

    def on_key(self, k):
        if k == "down":
            self.sel = max(0, min(len(self.rows) - 1, self.sel + 1))
        elif k == "up":
            self.sel = max(0, self.sel - 1)
        elif k == "delete":
            self.term()
            return
        else:
            return
        self.redraw()

    def _signal(self, sig):
        if not self.rows:
            return
        pid = self.rows[self.sel][0]
        if pid in (1, getpid()):
            self.wm.message("Procesos", "No se puede terminar %s." % ("init" if pid == 1 else "PyOS LOOK"))
            return
        try:
            kill(pid, sig)
        except OSError as e:
            self.wm.message("Procesos", "kill %d: %s" % (pid, e))
        sleep_ms(50)
        self.refresh()

    def term(self):
        self._signal(SIGTERM)

    def kill9(self):
        self._signal(SIGKILL)


# ================================================================== Aplicaciones (pkg)
class AppCenter(Window):
    icon = "apps"
    min_w = 420
    min_h = 260
    ROW = 44

    def __init__(self):
        Window.__init__(self, "Aplicaciones", 680, 470)
        self.pkgs = []
        self.sel = 0
        self.log = ""
        self.add_button(8, 8, 100, 28, "Instalar", self.install, True)
        self.add_button(114, 8, 110, 28, "Desinstalar", self.remove)
        self.add_button(230, 8, 100, 28, "Actualizar", self.refresh)
        self.refresh()

    def refresh(self):
        st, out = run_capture("/sbin/pkg.py", ["pkg", "avail"])
        pk = []
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            name, ver = parts[0], parts[1]
            rest = parts[2] if len(parts) > 2 else ""
            inst = rest.startswith("[i]")
            desc = rest[3:].strip() if inst else rest.strip()
            pk.append((name, ver, inst, desc))
        self.pkgs = pk
        self.sel = min(self.sel, max(0, len(pk) - 1))
        self.redraw()

    def current(self):
        return self.pkgs[self.sel] if 0 <= self.sel < len(self.pkgs) else None

    def run(self, verb):
        p = self.current()
        if p is None:
            return
        st, out = run_capture("/sbin/pkg.py", ["pkg", verb, p[0]])
        self.log = out.strip().splitlines()[-1] if out.strip() else "pkg %s %s: %s" % (verb, p[0], status_text(st))
        self.refresh()
        if p[0] == "look" and verb == "remove":
            self.wm.message("Aplicaciones", "Has desinstalado PyOS LOOK.\nSeguirá abierto hasta que salgas;\n"
                                            "después el selector arrancará en modo Term.")

    def install(self):
        self.run("install")

    def remove(self):
        p = self.current()
        if p is None:
            return
        self.wm.message("Aplicaciones", "¿Desinstalar %s?" % p[0], [("Desinstalar", lambda: self.run("remove")),
                                                                     ("Cancelar", None)])

    def draw_content(self, g, x, y, w, h):
        lx, ly, lw, lh = x + 8, y + 44, w - 16, h - 44 - 30
        g.append(("rect", lx, ly, lw, lh, T["field"]))
        g.append(("frame", lx, ly, lw, lh, T["line"], 1))
        for i, (name, ver, inst, desc) in enumerate(self.pkgs):
            ry = ly + 2 + i * self.ROW
            if ry + self.ROW > ly + lh:
                break
            sel = i == self.sel
            if sel:
                g.append(("rect", lx + 2, ry, lw - 4, self.ROW, T["sel"]))
            icon = {"arcade": "games", "look": "pyos", "juegos": "games"}.get(name, "apps")
            g.append(("bitmap", lx + 8, ry + 6, ICONS[icon][0], ICONS[icon][1], 2))
            col = T["sel_text"] if sel else T["text"]
            g.append(("text", lx + 50, ry + 4, "%s  %s" % (name, ver), col, None))
            g.append(("text", lx + 50, ry + 22, clip_text(desc, lw - 200), T["muted"], None))
            badge = "instalado" if inst else "disponible"
            g.append(("rect", lx + lw - 110, ry + 12, 96, 20, T["start"] if inst else T["btn"]))
            g.append(("text", lx + lw - 106, ry + 13, badge, 0xFFFFFF if inst else T["text"], None))
        info = self.log
        if not info and 0 <= self.sel < len(self.pkgs):
            info = self.pkgs[self.sel][3]          # descripción completa del seleccionado
        g.append(("text", x + 8, y + h - 24, clip_text(info or "Repositorio local: /var/pkg/repo", w - 16),
                  T["muted"], None))

    def on_mouse(self, kind, x, y, b):
        if kind == "wheel":
            if self.pkgs:
                self.sel = max(0, min(len(self.pkgs) - 1, max(0, self.sel + b)))
                self.redraw()
            return
        if kind in ("down", "double") and y >= 46:
            j = (y - 46) // self.ROW
            if 0 <= j < len(self.pkgs):
                self.sel = j
                self.redraw()

    def on_key(self, k):
        if k == "down":
            self.sel = max(0, min(len(self.pkgs) - 1, self.sel + 1))
        elif k == "up":
            self.sel = max(0, self.sel - 1)
        else:
            return
        self.redraw()


# ================================================================== Ajustes
class Settings(Window):
    icon = "settings"
    min_w = 700
    min_h = 440
    TABS = ["Apariencia", "Teclado", "Servicios", "Sistema", "Reloj"]

    def __init__(self):
        Window.__init__(self, "Ajustes", 700, 480)
        self.tab = 0
        self.svcs = []
        self.svc_sel = 0
        self.info = []
        self.msg = ""
        self.layout = "?"
        self.set_tab(0)

    def set_tab(self, i):
        self.tab = i
        self.buttons = []
        self.msg = ""
        bx = 170
        if i == 0:
            walls = [("Degradado", "")]
            try:
                walls += [(n.rsplit(".", 1)[0][:10], "/usr/share/images/" + n)
                          for n, t in sorted(listdir("/usr/share/images")) if n.lower().endswith(".bmp")][:3]
            except OSError:
                pass
            cur = SETTINGS.get("wallpaper", "")
            x = bx
            for label, path in walls:
                self.add_button(x, 226, 100, 30, label, self._wall(path), cur == path)
                x += 106
            self.add_button(x, 226, 90, 30, "Otra...", self._wall_other)
            mv = SETTINGS.get("mover", "auto")
            for j, (label, key) in enumerate((("Automático", "auto"), ("Contorno", "contorno"),
                                               ("Contenido", "completo"))):
                self.add_button(bx + j * 116, 326, 110, 30, label, self._mover(key), mv == key)
        elif i == 1:
            try:
                self.layout = kbdlayout()
            except OSError:
                self.layout = None
            self.add_button(bx, 80, 150, 34, "Español (es)", self._kbd("es"), self.layout == "es")
            self.add_button(bx + 160, 80, 150, 34, "Inglés (us)", self._kbd("us"), self.layout == "us")
        elif i == 2:
            self.load_svcs()
            self.add_button(bx, 14, 90, 28, "Iniciar", self._svc("start"), True)
            self.add_button(bx + 96, 14, 90, 28, "Detener", self._svc("stop"))
            self.add_button(bx + 192, 14, 100, 28, "Al arrancar", self._svc("enable"))
            self.add_button(bx + 298, 14, 110, 28, "No arrancar", self._svc("disable"))
        elif i == 3:
            self.load_info()
        elif i == 4:
            self.add_button(bx, 80, 50, 34, "-1h", self._tz(-1))
            self.add_button(bx + 56, 80, 50, 34, "+1h", self._tz(1))
        self.redraw()

    def _theme(self, key):
        def f():
            apply_theme(key)
            save_settings()
            self.wm.damage_all()
        return f

    def _wall(self, path):
        def f():
            self.wm.set_wallpaper(path)
            self.msg = "Fondo: %s" % (path or "degradado del tema")
            self.set_tab(0)
            self.msg = "Fondo: %s" % (path or "degradado del tema")
        return f

    def _mover(self, key):
        def f():
            SETTINGS["mover"] = key
            save_settings()
            self.set_tab(0)
            self.msg = {"auto": "Contorno en pantallas reales, contenido en la emulada.",
                        "contorno": "Se mueve un contorno; la ventana se coloca al soltar (rápido).",
                        "completo": "La ventana se redibuja entera mientras se mueve."}[key]
        return f

    def _wall_other(self):
        def done(v):
            if v:
                self._wall(v)()
        self.wm.add(Prompt("Fondo de escritorio", "Imagen BMP/PPM:", SETTINGS.get("wallpaper", "") or "/root/", done))

    def _kbd(self, lay):
        def f():
            try:
                kbdlayout(lay)
                self.msg = "Distribución cambiada a '%s'." % lay
            except OSError as e:
                self.msg = "No hay teclado PS/2 que configurar (%s)." % e
            self.set_tab(1)
            self.msg = self.msg
        return f

    def _tz(self, d):
        def f():
            try:
                v = int(SETTINGS.get("tz", "0")) + d
            except ValueError:
                v = d
            SETTINGS["tz"] = str(max(-12, min(14, v)))
            save_settings()
            self.redraw()
            self.wm.damage(self.wm.taskbar_rect())
        return f

    def load_svcs(self):
        st, out = run_capture("/sbin/svc.py", ["svc", "list"])
        self.svcs = [l for l in out.splitlines()[1:] if l.strip()]
        self.svc_sel = min(self.svc_sel, max(0, len(self.svcs) - 1))

    def _svc(self, verb):
        def f():
            if not self.svcs:
                return
            name = self.svcs[self.svc_sel].split()[0]
            st, out = run_capture("/sbin/svc.py", ["svc", verb, name])
            self.load_svcs()
            self.msg = out.strip().splitlines()[-1] if out.strip() else ""
            self.redraw()
        return f

    def load_info(self):
        info = []
        u = uname()
        info.append(("Sistema", "%s %s (%s)" % (u[0], u[2], u[4])))
        info.append(("Encendido", "%d min %d s" % (uptime_ms() // 60000, (uptime_ms() // 1000) % 60)))
        try:
            for l in read_file("/proc/meminfo").decode().splitlines()[:2]:
                k, v = l.split(":", 1)
                info.append((k, v.strip()))
        except OSError:
            pass
        try:
            s = statfs()
            info.append(("Disco", "%d de %d bloques libres" % (s["free_blocks"], s["blocks"])))
        except OSError:
            pass
        try:
            n = net_info()
            if not n.get("nic"):
                info.append(("Red", "solo 127.0.0.1 (%s)" % n.get("reason", "")))
            elif n.get("configured"):
                info.append(("Red", "%s/%s via %s [%s]" % (n["ip"], n["mask"], n["gw"], n["method"])))
                info.append(("DNS", n["dns"]))
            else:
                info.append(("Red", "sin configurar (DHCP: %s)" % n.get("dhcp", "?")))
        except OSError:
            pass
        for l in read_file("/proc/gfx").decode().splitlines():
            if ":" in l:
                k, v = l.split(":", 1)
                if k in ("adaptador", "resolución", "copia", "ratón"):
                    info.append(("Pantalla " + k, v.strip()))
        try:
            for l in read_file("/proc/cpuinfo").decode().splitlines():
                if l.lower().startswith(("model name", "modelo", "cpu")):
                    info.append(("CPU", l.split(":", 1)[1].strip()))
                    break
        except OSError:
            pass
        li = lx_available()
        info.append(("Linux", ("%s, kernel %s" % (li.get("distro"), li.get("kernel"))) if li.get("available")
                     else "no disponible (arranque nativo)"))
        self.info = info

    def draw_content(self, g, x, y, w, h):
        g.append(("rect", x, y, 156, h, T["btn"]))
        for i, t in enumerate(self.TABS):
            ry = y + 10 + i * 34
            if i == self.tab:
                g.append(("rect", x + 6, ry, 144, 30, T["accent"]))
            g.append(("text", x + 16, ry + 5, t, T["accent_text"] if i == self.tab else T["text"], None))
        bx = x + 170
        if self.tab == 0:
            g.append(("text", bx, y + 20, "Tema (se aplica al pulsarlo):", T["text"], None))
            for j, key in enumerate(sorted(THEMES)):
                th = THEMES[key]
                px = bx + j * 128
                if SETTINGS["theme"] == key:
                    g.append(("frame", px, y + 60, 122, 130, T["accent"], 2))
                g.append(("vgrad", px + 4, y + 64, 114, 60, th["desk1"], th["desk2"]))
                g.append(("rect", px + 16, y + 76, 84, 40, th["win"]))
                g.append(("frame", px + 16, y + 76, 84, 40, th["btn_edge"], 1))
                g.append(("rect", px + 16, y + 76, 84, 10, th["title1"]))
                g.append(("rect", px + 4, y + 124, 114, 14, th["task"]))
                g.append(("text", px + 6, y + 150, th["name"], T["text"], None))
                if SETTINGS["theme"] == key:
                    g.append(("text", px + 6, y + 166, "(actual)", T["muted"], None))
            g.append(("text", bx, y + 200, "Fondo de escritorio:", T["text"], None))
            g.append(("text", bx, y + 266, clip_text("BMP o PPM; se amplía hasta cubrir la pantalla.", w - 186),
                      T["muted"], None))
            g.append(("text", bx, y + 302, "Al mover y redimensionar ventanas:", T["text"], None))
        elif self.tab == 1:
            g.append(("text", bx, y + 20, "Distribución del teclado PS/2:", T["text"], None))
            g.append(("text", bx, y + 44, "Actual: %s" % (self.layout or "sin teclado PS/2"), T["muted"], None))
        elif self.tab == 2:
            g.append(("rect", bx, y + 54, w - 186, h - 100, T["field"]))
            for i, l in enumerate(self.svcs):
                ry = y + 58 + i * 22
                if i == self.svc_sel:
                    g.append(("rect", bx + 2, ry, w - 190, 22, T["sel"]))
                g.append(("text", bx + 6, ry + 2, clip_text(l, w - 200), T["text"], None))
        elif self.tab == 3:
            for i, (k, v) in enumerate(self.info):
                g.append(("text", bx, y + 16 + i * 24, k, T["muted"], None))
                g.append(("text", bx + 170, y + 16 + i * 24, clip_text(v, w - 360), T["text"], None))
        elif self.tab == 4:
            g.append(("text", bx, y + 20, "Hora mostrada: %s (reloj del firmware %+d h)" % (clock_str(), int(SETTINGS.get("tz", "0"))),
                      T["text"], None))
            g.append(("text", bx, y + 44, "VirtualBox y QEMU dan la hora local del host al firmware.", T["muted"], None))
        if self.msg:
            g.append(("text", bx, y + h - 26, clip_text(self.msg, w - 186), T["accent"], None))

    def on_mouse(self, kind, x, y, b):
        if kind == "down" and x < 156:
            i = (y - 10) // 34
            if 0 <= i < len(self.TABS):
                self.set_tab(i)
        elif kind == "down" and self.tab == 0 and 60 <= y < 182:
            j = (x - 170) // 128
            keys = sorted(THEMES)
            if 0 <= j < len(keys) and (x - 170) % 128 < 122:
                self._theme(keys[j])()
        elif kind == "down" and self.tab == 2 and y >= 58:
            j = (y - 58) // 22
            if 0 <= j < len(self.svcs):
                self.svc_sel = j
                self.redraw()

    def on_key(self, k):
        if k == "down":
            self.set_tab((self.tab + 1) % len(self.TABS))
        elif k == "up":
            self.set_tab((self.tab - 1) % len(self.TABS))


# ================================================================== Acerca de
class About(Window):
    icon = "info"
    resizable = False

    def __init__(self):
        Window.__init__(self, "Acerca de PyOS LOOK", 560, 330)

    def draw_content(self, g, x, y, w, h):
        g.append(("vgrad", x, y, w, 110, T["desk1"], T["desk2"]))
        g.append(("bitmap", x + 24, y + 24, LOGO, {"#": 0xFFFFFF}, 7))
        g.append(("text", x + 230, y + 30, "PyOS LOOK " + VERSION, 0xFFFFFF, None))
        g.append(("text", x + 230, y + 54, "entorno gráfico de PyOS", 0xFFFFFF, None))
        lines = [
            "Kernel, ventanas y aplicaciones: 100% Python.",
            "Pantalla: framebuffer real del adaptador de vídeo,",
            "ratón y teclado PS/2 manejados por el kernel PyOS.",
            "",
            "%s %dx%d" % (self.wm.info.get("adapter", "?"), self.wm.W, self.wm.H),
            "",
            "Your machine. Your system. Your rules.",
        ]
        for i, l in enumerate(lines):
            g.append(("text", x + 24, y + 126 + i * FH, clip_text(l, w - 48),
                      T["accent"] if i == len(lines) - 1 else T["text"], None))


# ================================================================== menús
def launch(wm, cls, *args):
    def f():
        wm.add(cls(*args))
    return f


def launch_app(wm, name, ctor):
    """Para aplicaciones de terceros: un fallo al construir la ventana se atribuye a la app."""
    def f():
        try:
            win = ctor()
        except Exception as e:
            wm.report(None, e, "al abrirse", False, name)
            return
        wm.add(win)
    return f


def unsaved_note(wm):
    names = [w.title for w in wm.wins if w.unsaved()]
    if not names:
        return ""
    return "\n\nHay cambios sin guardar en:\n" + "\n".join("  · " + n for n in names[:6])


def exit_to_term(wm):
    def f():
        def go():
            wm.exit_code = 2
            wm.running = False
        warn = unsaved_note(wm)
        if warn:
            wm.message("Salir de LOOK", "¿Salir a PyOS Term?" + warn, [("Salir", go), ("Cancelar", None)], 1)
        else:
            go()
    return f


def power(wm, how):
    def f():
        def go():
            wm.running = False
            wm.exit_code = 3 if how == "poweroff" else 4
        warn = unsaved_note(wm)
        wm.message("Apagar" if how == "poweroff" else "Reiniciar",
                   "¿%s el equipo?%s" % ("Apagar" if how == "poweroff" else "Reiniciar", warn),
                   [("Sí", go), ("Cancelar", None)], 1 if warn else 0)
    return f


def games(wm):
    def f():
        wm.add(GameCenter())
    return f


def start_menu_items(wm):
    return [
        ("Terminal", "terminal", launch(wm, Terminal)),
        ("Archivos", "folder", launch(wm, Files)),
        ("Notas", "notes", launch(wm, Notes)),
        ("Procesos", "procs", launch(wm, Procs)),
        ("Navegador", "web", launch(wm, Browser)),
        ("Paint", "paint", launch(wm, Paint)),
        ("Imágenes", "image", launch(wm, ImageViewer, "/usr/share/images/paisaje.bmp")),
        ("Calculadora", "calc", launch(wm, Calculator)),
    ] + [(name, icon if icon in ICONS else "app", launch_app(wm, name, ctor))
         for name, icon, ctor in LOOK_APPS] + [
        ("Aplicaciones", "apps", launch(wm, AppCenter)),
        ("Ajustes", "settings", launch(wm, Settings)),
        ("Juegos", "games", games(wm)),
        ("Ayuda", "info", launch(wm, Help)),
        ("Acerca de", "info", launch(wm, About)),
        None,
        ("Salir a PyOS Term", "terminal", exit_to_term(wm)),
        ("Reiniciar", "power", power(wm, "reboot")),
        ("Apagar", "power", power(wm, "poweroff")),
    ]


def desktop_menu_items(wm):
    def next_theme():
        keys = sorted(THEMES)
        apply_theme(keys[(keys.index(SETTINGS["theme"]) + 1) % len(keys)])
        save_settings()
        wm.damage_all()
    return [
        ("Nueva terminal", "terminal", launch(wm, Terminal)),
        ("Archivos", "folder", launch(wm, Files)),
        ("Cambiar tema", "settings", next_theme),
        ("Ajustes", "settings", launch(wm, Settings)),
        None,
        ("Acerca de", "info", launch(wm, About)),
    ]


def desktop_icons(wm):
    return [
        ("Terminal", "terminal", launch(wm, Terminal)),
        ("Archivos", "folder", launch(wm, Files)),
        ("Notas", "notes", launch(wm, Notes)),
        ("Procesos", "procs", launch(wm, Procs)),
        ("Apps", "apps", launch(wm, AppCenter)),
        ("Ajustes", "settings", launch(wm, Settings)),
        ("Juegos", "games", games(wm)),
        ("Acerca de", "info", launch(wm, About)),
        ("Navegador", "web", launch(wm, Browser)),
        ("Paint", "paint", launch(wm, Paint)),
        ("Imágenes", "image", launch(wm, ImageViewer, "/usr/share/images/paisaje.bmp")),
        ("Calculadora", "calc", launch(wm, Calculator)),
    ]
