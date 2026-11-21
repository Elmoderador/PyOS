# /lib/look/core.py — PyOS LOOK: gestor de ventanas, escritorio y kit de interfaz.
# Se carga con include(). Todo se dibuja con órdenes gfx_draw que ejecuta el kernel.

FW, FH = 8, 19                  # fuente del kernel (la misma de la consola UEFI)
TITLE_H = 26
BORDER = 1
SHADOW = 4
TASK_H = 34
ICON_GRID = 88
DOUBLE_MS = 450
CONF = "/etc/look.conf"
VERSION = "1.0.0"
# Versión de la API para aplicaciones de terceros (Window, LOOK_APPS, órdenes de dibujo,
# eventos). Sube solo cuando un cambio rompe plugins existentes; ver CHANGELOG.md.
LOOK_API = 1

THEMES = {
    "azul": {
        "name": "Azul", "desk1": 0x10203F, "desk2": 0x3D6AA8, "logo": 0x4A77B4,
        "win": 0xF3F4F6, "text": 0x111827, "muted": 0x6B7280, "line": 0xD1D5DB,
        "title1": 0x2F6FDB, "title2": 0x1D4ED8, "title_text": 0xFFFFFF,
        "title_off1": 0xB8BEC8, "title_off2": 0x9CA3AF, "title_off_text": 0xF9FAFB,
        "task": 0x0F172A, "task_btn": 0x1E293B, "task_on": 0x334155, "task_text": 0xE5E7EB,
        "accent": 0x2563EB, "accent_text": 0xFFFFFF, "sel": 0xDBEAFE, "sel_text": 0x1E3A8A,
        "btn": 0xE5E7EB, "btn_edge": 0x9CA3AF, "field": 0xFFFFFF, "danger": 0xDC2626,
        "term_bg": 0x0B1220, "term_fg": 0xD1FAE5, "start": 0x10B981, "menu": 0xFFFFFF,
        "shadow": 0x0A0F1C,
    },
    "grafito": {
        "name": "Grafito", "desk1": 0x111111, "desk2": 0x3A3A3A, "logo": 0x4A4A4A,
        "win": 0x262626, "text": 0xE5E5E5, "muted": 0xA3A3A3, "line": 0x404040,
        "title1": 0x525252, "title2": 0x404040, "title_text": 0xFAFAFA,
        "title_off1": 0x2E2E2E, "title_off2": 0x262626, "title_off_text": 0x9CA3AF,
        "task": 0x0A0A0A, "task_btn": 0x1F1F1F, "task_on": 0x3F3F46, "task_text": 0xE5E5E5,
        "accent": 0xF59E0B, "accent_text": 0x111111, "sel": 0x3F3F46, "sel_text": 0xFDE68A,
        "btn": 0x3A3A3A, "btn_edge": 0x5A5A5A, "field": 0x171717, "danger": 0xEF4444,
        "term_bg": 0x050505, "term_fg": 0xF5F5F5, "start": 0xF59E0B, "menu": 0x262626,
        "shadow": 0x000000,
    },
    "bosque": {
        "name": "Bosque", "desk1": 0x0B2B1F, "desk2": 0x3F7A5C, "logo": 0x4E8A6A,
        "win": 0xF4F7F2, "text": 0x14261C, "muted": 0x5F7466, "line": 0xCBD8CC,
        "title1": 0x2F855A, "title2": 0x276749, "title_text": 0xFFFFFF,
        "title_off1": 0xB7C4BA, "title_off2": 0xA0AFA4, "title_off_text": 0xF7FAF7,
        "task": 0x0F1F17, "task_btn": 0x1C3327, "task_on": 0x2D4F3C, "task_text": 0xE6F2EA,
        "accent": 0x2F855A, "accent_text": 0xFFFFFF, "sel": 0xD5EFDF, "sel_text": 0x1C4532,
        "btn": 0xE3EBE4, "btn_edge": 0x93A89A, "field": 0xFFFFFF, "danger": 0xC53030,
        "term_bg": 0x0A1610, "term_fg": 0xC6F6D5, "start": 0xF6AD55, "menu": 0xFFFFFF,
        "shadow": 0x06120C,
    },
    "contraste": {
        # alto contraste: negro, blanco y amarillo; bordes gruesos y nada de grises tenues
        "name": "Contraste", "desk1": 0x000000, "desk2": 0x000000, "logo": 0x3A3A00,
        "win": 0x000000, "text": 0xFFFFFF, "muted": 0xE5E5E5, "line": 0xFFFFFF,
        "title1": 0xFFD400, "title2": 0xFFD400, "title_text": 0x000000,
        "title_off1": 0x3A3A3A, "title_off2": 0x3A3A3A, "title_off_text": 0xFFFFFF,
        "task": 0x000000, "task_btn": 0x1A1A1A, "task_on": 0x3A3A3A, "task_text": 0xFFFFFF,
        "accent": 0xFFD400, "accent_text": 0x000000, "sel": 0xFFD400, "sel_text": 0x000000,
        "btn": 0x000000, "btn_edge": 0xFFFFFF, "field": 0x000000, "danger": 0xFF3B30,
        "term_bg": 0x000000, "term_fg": 0xFFFFFF, "start": 0xFFD400, "menu": 0x000000,
        "shadow": 0x3A3A3A,
    },
}
T = dict(THEMES["azul"])
SETTINGS = {"theme": "azul", "tz": "0"}
# Aplicaciones de terceros: cada .py de APPS_DIR se carga al arrancar y añade aquí
# (nombre, icono, constructor). Ver docs/LOOK.md, "Crear aplicaciones para LOOK".
APPS_DIR = "/usr/share/look/apps"
REAP = []                             # hijos ya abandonados que hay que recoger (sin zombis)


def reap_later(pid):
    if pid is not None and pid not in REAP:
        REAP.append(pid)


CLIPBOARD = [""]                      # portapapeles de LOOK (texto), compartido por todas las apps


def clip_set(text):
    CLIPBOARD[0] = text


def clip_get():
    return CLIPBOARD[0]
LOOK_APPS = []
PLUGIN_ERRORS = []


def load_settings():
    try:
        for line in read_file(CONF).decode().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                SETTINGS[k.strip()] = v.strip()
    except OSError:
        pass
    apply_theme(SETTINGS.get("theme", "azul"))


def save_settings():
    write_file(CONF, "".join("%s=%s\n" % (k, SETTINGS[k]) for k in sorted(SETTINGS)))
    sync()


def apply_theme(name):
    if name not in THEMES:
        name = "azul"
    SETTINGS["theme"] = name
    T.clear()
    T.update(THEMES[name])


# ------------------------------------------------------------------ rectángulos
def rinter(a, b):
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[0] + a[2], b[0] + b[2])
    y1 = min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def runion(a, b):
    x0 = min(a[0], b[0])
    y0 = min(a[1], b[1])
    x1 = max(a[0] + a[2], b[0] + b[2])
    y1 = max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def rsub(a, b):
    """a menos b: hasta 4 rectángulos que cubren lo de a que no está en b."""
    i = rinter(a, b)
    if i is None:
        return [a]
    ax, ay, aw, ah = a
    ix, iy, iw, ih = i
    out = []
    if iy > ay:
        out.append((ax, ay, aw, iy - ay))                               # arriba
    if iy + ih < ay + ah:
        out.append((ax, iy + ih, aw, ay + ah - iy - ih))                # abajo
    if ix > ax:
        out.append((ax, iy, ix - ax, ih))                               # izquierda
    if ix + iw < ax + aw:
        out.append((ix + iw, iy, ax + aw - ix - iw, ih))                # derecha
    return out


def rin(r, x, y):
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


def clip_text(s, maxw):
    n = maxw // FW
    if n <= 0:
        return ""
    if len(s) <= n:
        return s
    return s[:max(0, n - 2)] + ".." if n > 2 else s[:n]


def fmt_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KiB" % (n / 1024.0)
    return "%.1f MiB" % (n / 1048576.0)


# ------------------------------------------------------------------ teclado
SEQS = {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "[H": "home", "[F": "end",
        "[3~": "delete", "[5~": "pgup", "[6~": "pgdn", "[2~": "insert", "[29~": "super",
        "OP": "f1", "OQ": "f2", "OR": "f3", "OS": "f4", "[15~": "f5", "[17~": "f6",
        "[18~": "f7", "[19~": "f8", "[20~": "f9", "[21~": "f10", "[23~": "f11", "[24~": "f12"}


class KeyParser:
    def __init__(self):
        self.pending = b""

    def feed(self, data):
        data = self.pending + data
        self.pending = b""
        out = []
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1B:
                if i + 1 >= n:
                    out.append("esc")
                    i += 1
                    continue
                nb = data[i + 1]
                if nb == 0x5B or nb == 0x4F:
                    j = i + 2
                    while j < n and not (0x40 <= data[j] <= 0x7E and (nb == 0x4F or data[j] != 0x5B)):
                        j += 1
                    if j >= n:
                        self.pending = data[i:]
                        break
                    seq = data[i + 1:j + 1].decode("ascii", "replace")
                    out.append(SEQS.get(seq, "?"))
                    i = j + 1
                    continue
                if nb == 0x09:
                    out.append("alt-tab")
                    i += 2
                    continue
                if 0x61 <= nb <= 0x7A:
                    out.append("alt-" + chr(nb))
                    i += 2
                    continue
                out.append("esc")
                i += 1
                continue
            if b in (0x0D, 0x0A):
                out.append("enter")
            elif b == 0x09:
                out.append("tab")
            elif b in (0x7F, 0x08):
                out.append("backspace")
            elif b < 0x20:
                out.append("ctrl-" + chr(b + 96))
            elif b < 0x80:
                out.append(chr(b))
            else:
                ln = 2 if b < 0xE0 else (3 if b < 0xF0 else 4)
                if i + ln > n:
                    self.pending = data[i:]
                    break
                out.append(data[i:i + ln].decode("utf-8", "replace"))
                i += ln
                continue
            i += 1
        return out


def printable(k):
    return len(k) == 1 and k >= " "


# ------------------------------------------------------------------ dibujo
def d_button(g, x, y, w, h, label, pressed=False, primary=False, enabled=True, hover=False):
    bg = T["accent"] if primary else T["btn"]
    fg = T["accent_text"] if primary else T["text"]
    if not enabled:
        fg = T["muted"]
    if pressed:
        bg = T["sel"]
        fg = T["sel_text"]
    elif hover and enabled and not primary:
        bg = T["sel"]
        fg = T["sel_text"]
    g.append(("rect", x, y, w, h, bg))
    edge = T["accent"] if primary or (hover and enabled) else T["btn_edge"]
    g.append(("frame", x, y, w, h, edge, 2 if hover and enabled and primary else 1))
    s = clip_text(label, w - 8)
    g.append(("text", x + (w - FW * len(s)) // 2, y + (h - FH) // 2, s, fg, None))


def d_field(g, x, y, w, h, text, focused, cursor=None):
    g.append(("rect", x, y, w, h, T["field"]))
    g.append(("frame", x, y, w, h, T["accent"] if focused else T["btn_edge"], 1))
    vis = (w - 8) // FW
    start = 0
    if cursor is not None and cursor > vis - 1:
        start = cursor - vis + 1
    s = text[start:start + vis]
    g.append(("text", x + 4, y + (h - FH) // 2, s, T["text"], None))
    if focused and cursor is not None:
        g.append(("rect", x + 4 + (cursor - start) * FW, y + 4, 2, h - 8, T["accent"]))


def d_scrollbar(g, x, y, h, total, visible, first):
    g.append(("rect", x, y, 10, h, T["line"]))
    if total <= visible:
        return
    th = max(16, h * visible // total)
    ty = y + (h - th) * first // max(1, total - visible)
    g.append(("rect", x + 1, ty, 8, th, T["muted"]))


class Btn:
    def __init__(self, x, y, w, h, label, action, primary=False):
        self.r = (x, y, w, h)
        self.label = label
        self.action = action
        self.primary = primary
        self.enabled = True
        self.down = False


# ------------------------------------------------------------------ ventana base
class Window:
    resizable = True
    min_w = 260
    min_h = 160
    icon = "app"
    kind = "app"
    snapped = None                    # "left"/"right" si está encajada en un borde

    def __init__(self, title, w, h):
        self.title = title
        self.w = w
        self.h = h
        self.x = 0
        self.y = 0
        self.wm = None
        self.minimized = False
        self.maximized = False
        self.saved = None
        self.buttons = []
        self.focus_field = None

    # geometría
    def rect(self):
        return (self.x, self.y, self.w, self.h)

    def outer(self):
        return (self.x, self.y, self.w + SHADOW, self.h + SHADOW)

    def content(self):
        return (self.x + BORDER, self.y + TITLE_H, self.w - 2 * BORDER, self.h - TITLE_H - BORDER)

    def title_btns(self):
        bx = self.x + self.w - 26
        y = self.y + 3
        r = [("close", (bx, y, 22, 20))]
        if self.resizable:
            r.append(("max", (bx - 24, y, 22, 20)))
        r.append(("min", (bx - (48 if self.resizable else 24), y, 22, 20)))
        return r

    def grip(self):
        return (self.x + self.w - 14, self.y + self.h - 14, 14, 14)

    # utilidades para las apps
    def redraw(self):
        if self.wm is not None and not self.minimized:
            self.wm.damage(self.rect())

    def add_button(self, x, y, w, h, label, action, primary=False):
        b = Btn(x, y, w, h, label, action, primary)
        self.buttons.append(b)
        return b

    # dibujo
    def draw(self, g, active):
        x, y, w, h = self.rect()
        g.append(("rect", x + SHADOW, y + h, w, SHADOW, T["shadow"]))
        g.append(("rect", x + w, y + SHADOW, SHADOW, h - SHADOW, T["shadow"]))
        g.append(("frame", x, y, w, h, T["title2"] if active else T["btn_edge"], 1))
        g.append(("vgrad", x + 1, y + 1, w - 2, TITLE_H - 1,
                  T["title1"] if active else T["title_off1"], T["title2"] if active else T["title_off2"]))
        tcol = T["title_text"] if active else T["title_off_text"]
        g.append(("bitmap", x + 6, y + 5, ICONS.get(self.icon, ICONS["app"])[0],
                  ICONS.get(self.icon, ICONS["app"])[1], 1))
        g.append(("text", x + 26, y + 4, clip_text(self.title, w - 110), tcol, None))
        for kind, r in self.title_btns():
            bx, by, bw, bh = r
            if kind == "close":
                g.append(("rect", bx, by, bw, bh, T["danger"] if active else T["title_off2"]))
                g.append(("text", bx + 7, by + 1, "x", 0xFFFFFF, None))
            elif kind == "max":
                g.append(("frame", bx + 6, by + 5, 10, 9, tcol, 1))
                g.append(("rect", bx + 6, by + 5, 10, 2, tcol))
            else:
                g.append(("rect", bx + 6, by + 13, 10, 2, tcol))
        cx, cy, cw, ch = self.content()
        g.append(("rect", cx, cy, cw, ch, T["win"]))
        g.append(("clip_push", cx, cy, cw, ch))
        self.draw_content(g, cx, cy, cw, ch)
        hv = self.wm.hover if self.wm is not None else None
        for b in self.buttons:
            bx, by, bw, bh = b.r
            d_button(g, cx + bx, cy + by, bw, bh, b.label, b.down, b.primary, b.enabled,
                     hv is not None and hv[0] is self and hv[1] is b)
        g.append(("clip_pop",))
        if self.resizable and not self.maximized:
            gx, gy, gw, gh = self.grip()
            for i in range(3):
                g.append(("rect", gx + 4 + 3 * i, gy + 10 - 3 * i, 8 - 3 * i, 1, T["muted"]))

    def draw_content(self, g, x, y, w, h):
        pass

    # eventos (coordenadas locales al contenido)
    def mouse(self, kind, x, y, buttons):
        if kind == "down":
            for b in self.buttons:
                if b.enabled and rin(b.r, x, y):
                    b.down = True
                    self.redraw()
                    return
        elif kind == "up":
            hit = None
            for b in self.buttons:
                if b.down:
                    b.down = False
                    self.redraw()
                    if rin(b.r, x, y):
                        hit = b
            if hit is not None:
                hit.action()
                return
        self.on_mouse(kind, x, y, buttons)

    def on_mouse(self, kind, x, y, buttons):
        pass

    def on_key(self, k):
        pass

    def tick(self, now):
        pass

    def on_resize(self):
        pass

    def on_close(self):
        return True

    def unsaved(self):
        """True si cerrar la ventana perdería trabajo (Notas, Paint)."""
        return False

    def close(self):
        if self.wm is not None:
            self.wm.close(self)


# ------------------------------------------------------------------ diálogos
class Prompt(Window):
    resizable = False
    icon = "notes"

    def __init__(self, title, question, value, callback):
        Window.__init__(self, title, 420, 150)
        self.question = question
        self.value = value
        self.cur = len(value)
        self.callback = callback
        self.add_button(220, 82, 90, 28, "Aceptar", self.ok, True)
        self.add_button(318, 82, 90, 28, "Cancelar", self.close)

    def draw_content(self, g, x, y, w, h):
        g.append(("text", x + 12, y + 12, clip_text(self.question, w - 24), T["text"], None))
        d_field(g, x + 12, y + 40, w - 24, 28, self.value, True, self.cur)

    def ok(self):
        v = self.value
        self.close()
        self.callback(v)

    def on_key(self, k):
        if k == "enter":
            self.ok()
        elif k == "esc":
            self.close()
        elif k == "backspace" and self.cur > 0:
            self.value = self.value[:self.cur - 1] + self.value[self.cur:]
            self.cur -= 1
        elif k == "delete":
            self.value = self.value[:self.cur] + self.value[self.cur + 1:]
        elif k == "left":
            self.cur = max(0, self.cur - 1)
        elif k == "right":
            self.cur = min(len(self.value), self.cur + 1)
        elif k == "home":
            self.cur = 0
        elif k == "end":
            self.cur = len(self.value)
        elif k == "ctrl-v":
            t = clip_get().split("\n")[0]
            self.value = self.value[:self.cur] + t + self.value[self.cur:]
            self.cur += len(t)
        elif k == "ctrl-c":
            clip_set(self.value)
        elif printable(k):
            self.value = self.value[:self.cur] + k + self.value[self.cur:]
            self.cur += 1
        else:
            return
        self.redraw()


class Message(Window):
    resizable = False
    icon = "info"

    def __init__(self, title, text, buttons=None):
        lines = []
        for l in text.split("\n"):
            while len(l) > 84:                  # líneas largas (p. ej. un repr de error): partir
                lines.append(l[:84])
                l = "  " + l[84:]
            lines.append(l)
        w = max(320, min(720, 40 + FW * max(len(l) for l in lines)))
        Window.__init__(self, title, w, 110 + FH * len(lines))
        self.lines = lines
        bw = 100
        opts = buttons or [("Aceptar", None)]
        x = w - 12 - (bw + 8) * len(opts)
        for label, fn in opts:
            self.add_button(x, self.h - TITLE_H - 44, bw, 28, label, self._mk(fn), fn is not None)
            x += bw + 8

    def _mk(self, fn):
        def act():
            self.close()
            if fn is not None:
                fn()
        return act

    focus_i = 0

    def draw(self, g, active):
        Window.draw(self, g, active)
        if active and self.buttons:
            bx, by, bw, bh = self.buttons[self.focus_i % len(self.buttons)].r
            cx, cy, cw, ch = self.content()
            g.append(("frame", cx + bx - 3, cy + by - 3, bw + 6, bh + 6, T["accent"], 2))

    def draw_content(self, g, x, y, w, h):
        for i, line in enumerate(self.lines):
            g.append(("text", x + 16, y + 14 + i * FH, line, T["text"], None))

    def on_key(self, k):
        n = len(self.buttons)
        if k in ("tab", "right") and n:
            self.focus_i = (self.focus_i + 1) % n          # Tab y flechas mueven el foco
            self.redraw()
        elif k == "left" and n:
            self.focus_i = (self.focus_i - 1) % n
            self.redraw()
        elif k in ("enter", " ") and n:
            self.buttons[self.focus_i % n].action()       # Intro/espacio: el botón con foco
        elif k in ("enter", "esc"):
            self.close()


# ------------------------------------------------------------------ menú emergente
class Menu:
    ITEM_H = 26

    def __init__(self, items, x, y, on_pick=None):
        self.items = items                     # [(etiqueta, icono, acción)] o None (separador)
        self.w = 8 + 26 + FW * max(len(i[0]) for i in items if i) + 24
        self.h = 8 + sum(self.ITEM_H if i else 9 for i in items)
        self.x = x
        self.y = y - self.h if y - self.h >= 0 else y
        self.sel = -1

    def rect(self):
        return (self.x, self.y, self.w + SHADOW, self.h + SHADOW)

    def body(self):
        return (self.x, self.y, self.w, self.h)

    def item_at(self, mx, my):
        y = self.y + 4
        for i, it in enumerate(self.items):
            hh = self.ITEM_H if it else 9
            if it and self.x <= mx < self.x + self.w and y <= my < y + hh:
                return i
            y += hh
        return -1

    def draw(self, g):
        x, y, w, h = self.x, self.y, self.w, self.h
        g.append(("rect", x + SHADOW, y + h, w, SHADOW, T["shadow"]))
        g.append(("rect", x + w, y + SHADOW, SHADOW, h - SHADOW, T["shadow"]))
        g.append(("rect", x, y, w, h, T["menu"]))
        g.append(("frame", x, y, w, h, T["btn_edge"], 1))
        yy = y + 4
        for i, it in enumerate(self.items):
            if it is None:
                g.append(("rect", x + 8, yy + 4, w - 16, 1, T["line"]))
                yy += 9
                continue
            label, icon, act = it
            if i == self.sel:
                g.append(("rect", x + 3, yy, w - 6, self.ITEM_H, T["accent"]))
            col = T["accent_text"] if i == self.sel else T["text"]
            if icon:
                g.append(("bitmap", x + 8, yy + 5, ICONS[icon][0], ICONS[icon][1], 1))
            g.append(("text", x + 32, yy + 3, label, col, None))
            yy += self.ITEM_H

    def move_sel(self, d):
        n = len(self.items)
        i = self.sel
        for _ in range(n):
            i = (i + d) % n
            if self.items[i]:
                self.sel = i
                return


# ------------------------------------------------------------------ gestor de ventanas
class WM:
    def __init__(self, info):
        self.W = info["width"]
        self.H = info["height"]
        self.info = info
        self.wins = []
        self.dmg = []
        self.running = True
        self.exit_code = 0
        self.menu = None
        self.drag = None                     # (modo, ventana, dx, dy, rect inicial)
        self.snap = None                     # zona de encaje durante un arrastre
        self.ghost = None                    # contorno de la ventana que se mueve (modo contorno)
        self.task_more = None                # botón "+N" de la barra: (rect, ventanas que no caben)
        self.broken = []                     # ventanas que fallaron: (ventana, excepción, dónde)
        self.wall = None
        self.mx = self.W // 2
        self.my = self.H // 2
        self.buttons = 0
        self.keys = KeyParser()
        self.last_click = (0, None)
        self.desk_sel = -1
        self.icons = []
        self.clock_text = ""
        self.task_rects = []
        self.focus_icons = False
        self.notice = ""
        self.toasts = []                     # [texto, hasta_ms]
        self.load_wallpaper()
        self.ev_time = 0
        self.last_up = -10000

    # ---------------------------------------------------------- ventanas
    def add(self, win, x=None, y=None):
        win.wm = self
        n = len(self.wins)
        win.w = min(win.w, self.W - 20)
        win.h = min(win.h, self.H - TASK_H - 20)
        # en cascada alrededor del centro; si apenas cabe, centrada (en 800x600 no se pega a la esquina)
        shift = 24 * (n % 6) - 60
        room_x, room_y = self.W - win.w, self.H - TASK_H - win.h
        if x is None:
            x = room_x // 2 if room_x < 160 else max(0, min(room_x - 10, room_x // 2 + shift))
        if y is None:
            y = room_y // 2 if room_y < 160 else max(0, min(room_y - 10, room_y // 2 + shift))
        win.x, win.y = max(0, x), max(0, y)
        self.wins.append(win)
        self.damage_box(win.rect())
        self.damage(self.taskbar_rect())
        win.on_resize()
        return win

    def close(self, win):
        if win not in self.wins or not win.on_close():
            return
        self.wins.remove(win)
        self.damage_box(win.rect())
        self.damage(self.taskbar_rect())
        if self.drag and self.drag[1] is win:
            self.drag = None
        top = self.top()
        if top is not None:
            self.damage(top.rect())

    def top(self):
        for w in reversed(self.wins):
            if not w.minimized:
                return w
        return None

    def focus(self, win):
        old = self.top()
        if win in self.wins:
            self.wins.remove(win)
            self.wins.append(win)
        win.minimized = False
        if old is not None and old is not win:
            self.damage(old.rect())
        self.damage_box(win.rect())
        self.damage(self.taskbar_rect())

    def minimize(self, win):
        win.minimized = True
        self.damage_box(win.rect())
        self.damage(self.taskbar_rect())
        top = self.top()
        if top is not None:
            self.damage(top.rect())

    def toggle_max(self, win):
        self.damage_box(win.rect())
        if win.maximized:
            win.x, win.y, win.w, win.h = win.saved
            win.maximized = False
        else:
            win.saved = win.rect()
            win.x, win.y, win.w, win.h = 0, 0, self.W - SHADOW, self.H - TASK_H - SHADOW
            win.maximized = True
        win.on_resize()
        self.damage_box(win.rect())

    def find(self, cls):
        for w in self.wins:
            if isinstance(w, cls):
                return w
        return None

    def message(self, title, text, buttons=None, default=0):
        """default: botón con el foco al abrir (Intro lo pulsa). En avisos que pueden hacer
        perder trabajo conviene que sea el seguro (Cancelar)."""
        m = Message(title, text, buttons)
        m.focus_i = default
        return self.add(m)

    # ---------------------------------------------------------- daños y dibujo
    def damage(self, r):
        r = rinter(r, (0, 0, self.W, self.H))
        if r is not None:
            self.dmg.append(r)

    def damage_box(self, r):
        """Daña un rectángulo opaco con sombra como 3 piezas: el cuerpo (que tapa todo lo de
        debajo y permite saltarse el escritorio y las ventanas inferiores) y las dos tiras de sombra."""
        x, y, w, h = r
        self.damage((x, y, w, h))
        self.damage((x + w, y, SHADOW, h + SHADOW))
        self.damage((x, y + h, w, SHADOW))

    def damage_move(self, old, new):
        """Una ventana pasa de `old` a `new`: se daña la nueva (la ventana tapa lo de debajo)
        y solo lo que queda al descubierto de la vieja, con su sombra."""
        self.damage_box(new)
        ox, oy, ow, oh = old
        for piece in rsub((ox, oy, ow + SHADOW, oh + SHADOW), new):
            self.damage(piece)

    def damage_all(self):
        self.dmg = [(0, 0, self.W, self.H)]

    def taskbar_rect(self):
        return (0, self.H - TASK_H, self.W, TASK_H)

    def _regions(self):
        rs = self.dmg
        self.dmg = []
        if not rs:
            return []
        rs.sort(key=lambda r: r[2] * r[3], reverse=True)
        out = []
        for r in rs:
            # Se funden solo si la unión no añade mucha superficie que no estaba dañada:
            # el menú y la barra de tareas se tocan, pero su unión es medio escritorio.
            changed = True
            while changed:
                changed = False
                for i in range(len(out)):
                    o = out[i]
                    u = runion(o, r)
                    it = rinter(o, r)
                    if it is not None and it[2] * it[3] * 2 >= min(o[2] * o[3], r[2] * r[3]):
                        r = u
                        out.pop(i)
                        changed = True
                        break
                    if u[2] * u[3] == o[2] * o[3]:       # ya contenida
                        r = o
                        out.pop(i)
                        changed = True
                        break
            out.append(r)
            if len(out) > 12:
                big = out[0]
                for o in out[1:]:
                    big = runion(big, o)
                out = [big]
        return out

    def flush(self):
        regions = self._regions()
        if not regions:
            return
        g = []
        for reg in regions:
            g.append(("clip",) + reg)
            self.draw_region(g, reg)
        g.append(("noclip",))
        gfx_draw(resolve_clips(g))

    def draw_region(self, g, reg):
        top = self.top()
        tb = self.taskbar_rect()
        only_bar = reg[1] >= tb[1]                  # la barra tapa a todo lo demás
        # oclusión: la ventana más alta que cubre toda la región tapa al escritorio y a las de debajo
        first = -1
        if self.menu is not None and not only_bar:
            mx, my, mw, mh = self.menu.body()
            if mx <= reg[0] and my <= reg[1] and mx + mw >= reg[0] + reg[2] and my + mh >= reg[1] + reg[3]:
                self.menu.draw(g)                  # el menú tapa toda la región
                return
        if not only_bar:
            i = len(self.wins) - 1
            while i >= 0 and first < 0:
                w = self.wins[i]
                if not w.minimized:
                    x, y, ww, hh = w.rect()
                    if x <= reg[0] and y <= reg[1] and x + ww >= reg[0] + reg[2] and y + hh >= reg[1] + reg[3]:
                        first = i
                i -= 1
            if first < 0:
                first = 0
                self.draw_desktop(g, reg)
        for w in ([] if only_bar else self.wins[first:]):
            if not w.minimized and rinter(w.outer(), reg) is not None:
                n = len(g)
                try:
                    w.draw(g, w is top)
                except Exception as e:
                    del g[n:]                   # lo que dibujó a medias, fuera
                    self.broken.append((w, e, "al dibujar"))
        if rinter(self.taskbar_rect(), reg) is not None:
            self.draw_taskbar(g)
        if self.menu is not None and rinter(self.menu.rect(), reg) is not None:
            self.menu.draw(g)
        if self.toasts:
            self.draw_toasts(g, reg)
        if self.snap is not None:
            g.append(("frame",) + self.snap_inner(self.snap) + (T["accent"], 3))
        if self.ghost is not None:
            g.append(("frame",) + self.ghost + (T["accent"], 3))

    def load_wallpaper(self):
        """Fondo de imagen: se escala por un entero hasta cubrir el escritorio y se centra."""
        self.wall = None
        p = SETTINGS.get("wallpaper", "")
        if not p:
            return
        try:
            w, h, px = load(p)
        except (OSError, ValueError) as e:
            self.notice = "fondo de escritorio: %s" % e
            return
        H = self.H - TASK_H
        k = 1
        while w // k > 2 * self.W or h // k > 2 * H:
            k += 1
        if k > 1:
            w, h, px = shrink(w, h, px, k)
        s = min(16, max(1, -(-self.W // w), -(-H // h)))
        self.wall = ((self.W - w * s) // 2, (H - h * s) // 2, w, h, bytes(px), s)

    def set_wallpaper(self, path):
        SETTINGS["wallpaper"] = path
        save_settings()
        self.load_wallpaper()
        self.damage_all()

    def draw_desktop(self, g, reg):
        H = self.H - TASK_H
        if self.wall is not None:
            g.append(("clip_push", 0, 0, self.W, H))
            g.append(("image",) + self.wall)
            g.append(("clip_pop",))
        else:
            g.append(("vgrad", reg[0], 0, reg[2], H, T["desk1"], T["desk2"]))
        lw = 6 * len(LOGO[0])
        lx = self.W - lw - 40
        ly = H - 6 * len(LOGO) - 50
        if rinter((lx, ly, lw, 6 * len(LOGO) + 30), reg) is not None:
            g.append(("bitmap", lx, ly, LOGO, {"#": T["logo"]}, 6))
            g.append(("text", lx + lw - FW * 14, ly + 6 * len(LOGO) + 8, "LOOK  v" + VERSION, T["logo"], None))
        for i, (label, icon, fn) in enumerate(self.icons):
            r = self.icon_rect(i)
            if rinter(r, reg) is None:
                continue
            x, y, w, h = r
            if i == self.desk_sel:
                g.append(("rect", x + 2, y + 2, w - 4, h - 4, T["accent"]))
            g.append(("bitmap", x + (w - 32) // 2, y + 8, ICONS[icon][0], ICONS[icon][1], 2))
            s = clip_text(label, ICON_GRID + 6)      # la etiqueta puede invadir el margen entre iconos
            g.append(("text", x + (w - FW * len(s)) // 2 + 1, y + 47, s, 0x000000, None))
            g.append(("text", x + (w - FW * len(s)) // 2, y + 46, s, 0xFFFFFF, None))

    def icon_rect(self, i):
        per_col = max(1, (self.H - TASK_H - 16) // ICON_GRID)
        return (12 + (i // per_col) * ICON_GRID, 12 + (i % per_col) * ICON_GRID, ICON_GRID - 8, ICON_GRID - 8)

    def draw_taskbar(self, g):
        y = self.H - TASK_H
        g.append(("rect", 0, y, self.W, TASK_H, T["task"]))
        g.append(("rect", 0, y, self.W, 1, T["task_on"]))
        on = self.menu is not None and self.menu.kind == "start"
        g.append(("rect", 4, y + 4, 92, TASK_H - 8, T["task_on"] if on else T["start"]))
        g.append(("bitmap", 10, y + 9, ICONS["pyos"][0], ICONS["pyos"][1], 1))
        g.append(("text", 32, y + 7, "PyOS", 0xFFFFFF if not on else T["task_text"], None))
        x = 104
        top = self.top()
        self.task_rects = []
        avail = self.W - x - 110
        n = max(1, len(self.wins))
        bw = max(60, min(200, avail // n - 4))
        fit = len(self.wins) if n * (bw + 4) <= avail + 4 else max(0, (avail - 48) // (bw + 4))
        self.task_more = None
        for k, w in enumerate(self.wins):
            if k >= fit:
                # las que no caben: un botón "+N" que abre su lista
                r = (x, y + 4, 44, TASK_H - 8)
                self.task_more = (r, self.wins[k:])
                g.append(("rect", r[0], r[1], r[2], r[3], T["task_btn"]))
                s = "+%d" % (len(self.wins) - k)
                g.append(("text", x + (44 - FW * len(s)) // 2, y + 7, s, T["task_text"], None))
                break
            r = (x, y + 4, bw, TASK_H - 8)
            self.task_rects.append((r, w))
            g.append(("rect", r[0], r[1], r[2], r[3], T["task_on"] if w is top else T["task_btn"]))
            if w is top:
                g.append(("rect", r[0], r[1] + r[3] - 2, r[2], 2, T["start"]))
            g.append(("bitmap", x + 6, y + 9, ICONS.get(w.icon, ICONS["app"])[0], ICONS.get(w.icon, ICONS["app"])[1], 1))
            g.append(("text", x + 26, y + 7, clip_text(w.title, bw - 30),
                      T["task_text"] if not w.minimized else T["muted"], None))
            x += bw + 4
        self.clock_text = clock_str()
        g.append(("text", self.W - 8 - FW * len(self.clock_text), y + 7, self.clock_text, T["task_text"], None))
        if self.notice:
            g.append(("text", self.W - 16 - FW * (len(self.clock_text) + len(self.notice)), y + 7,
                      self.notice, T["start"], None))

    # ---------------------------------------------------------- avisos
    def toast_rect(self, i):
        w = 340
        return (self.W - w - 10, self.H - TASK_H - 10 - (i + 1) * 50, w, 44)

    def toast(self, text, ms=3500):
        """Aviso breve abajo a la derecha (como una notificación)."""
        if len(self.toasts) >= 4:
            self.damage(self.toast_rect(0))
            self.toasts.pop(0)
            for i in range(len(self.toasts) + 1):
                self.damage(self.toast_rect(i))
        self.toasts.append([text, uptime_ms() + ms])
        self.damage(self.toast_rect(len(self.toasts) - 1))

    def draw_toasts(self, g, reg):
        for i, (text, until) in enumerate(self.toasts):
            r = self.toast_rect(i)
            if rinter(r, reg) is None:
                continue
            x, y, w, h = r
            g.append(("rect", x + SHADOW, y + SHADOW, w, h, T["shadow"]))
            g.append(("rect", x, y, w, h, T["win"]))
            g.append(("rect", x, y, 4, h, T["accent"]))
            g.append(("frame", x, y, w, h, T["btn_edge"], 1))
            lines = text.split("\n")
            for j, l in enumerate(lines[:2]):
                g.append(("text", x + 14, y + 4 + j * FH if len(lines) > 1 else y + 12, clip_text(l, w - 24),
                          T["text"], None))

    # ---------------------------------------------------------- entrada
    def open_menu(self, menu, kind):
        self.close_menu()
        menu.kind = kind
        self.menu = menu
        self.damage_box(menu.body())
        self.damage(self.taskbar_rect())

    def task_menu(self, w, x, y):
        def act(f):
            def g():
                f(w)
            return g
        items = [("Restaurar" if w.minimized else "Minimizar", "app",
                  act(self.focus if w.minimized else self.minimize))]
        if w.resizable:
            items.append(("Restaurar tamaño" if w.maximized else "Maximizar", "app", act(self.toggle_max)))
        items += [None, ("Cerrar", "power", act(self.close))]
        m = Menu(items, x, self.H - TASK_H)
        m.x = min(x, self.W - m.w - SHADOW)
        self.open_menu(m, "ctx")

    def popup(self, items, x, y):
        """Menú contextual bajo el puntero (o encima si no cabe)."""
        m = Menu(items, x, y)
        H = self.H - TASK_H
        m.y = y if y + m.h <= H else max(0, y - m.h)
        m.x = min(x, self.W - m.w - SHADOW)
        self.open_menu(m, "ctx")

    def close_menu(self):
        if self.menu is not None:
            self.damage_box(self.menu.body())
            self.damage(self.taskbar_rect())
            self.menu = None

    def handle_mouse(self, evs):
        for ev in evs:
            x, y, b = ev[0], ev[1], ev[2]
            # el doble clic se mide con la hora del kernel (cuando llegó el paquete del ratón),
            # no con la de proceso: así no depende de lo cargado que vaya LOOK
            self.ev_time = ev[3] if len(ev) > 3 else uptime_ms()
            prev = self.buttons
            self.mx, self.my = x, y
            dz = ev[4] if len(ev) > 4 else 0
            if dz:
                self.on_wheel(x, y, dz)
                if b == prev:
                    continue                    # solo rueda: no es un movimiento (no toca el hover)
            if b & 1 and not prev & 1:
                self.on_down(x, y, b)
            elif prev & 1 and not b & 1:
                self.on_up(x, y, b)
            elif b & 1:
                self.on_drag(x, y, b)
            elif self.menu is not None:
                i = self.menu.item_at(x, y)
                if i != self.menu.sel:
                    self.menu.sel = i
                    self.damage_box(self.menu.body())
            else:
                self.update_hover(x, y)
            if b & 2 and not prev & 2:
                self.on_right(x, y)
            self.buttons = b

    def on_wheel(self, x, y, dz):
        if self.menu is not None:
            self.menu.move_sel(1 if dz > 0 else -1)
            self.damage_box(self.menu.body())
            return
        w = self.win_at(x, y)
        if w is None:
            return
        cx, cy, cw, ch = w.content()
        if rin((cx, cy, cw, ch), x, y):
            w.mouse("wheel", x - cx, y - cy, dz)

    hover = None                       # (ventana, botón) bajo el puntero

    def update_hover(self, x, y):
        h = None
        w = self.win_at(x, y)
        if w is not None and w.buttons:
            cx, cy, cw, ch = w.content()
            for b in w.buttons:
                if b.enabled and rin(b.r, x - cx, y - cy):
                    h = (w, b)
                    break
        old = self.hover
        if (old is None) != (h is None) or (old is not None and (old[0] is not h[0] or old[1] is not h[1])):
            self.hover = h
            for it in (old, h):
                if it is not None and it[0] in self.wins:
                    cx, cy, cw, ch = it[0].content()
                    bx, by, bw, bh = it[1].r
                    self.damage((cx + bx, cy + by, bw, bh))

    def win_at(self, x, y):
        for w in reversed(self.wins):
            if not w.minimized and rin(w.rect(), x, y):
                return w
        return None

    def on_down(self, x, y, b):
        now = self.ev_time
        if self.menu is not None:
            if rin(self.menu.rect(), x, y):
                return
            self.close_menu()
            if y >= self.H - TASK_H and x < 100:
                return                          # el clic en PyOS cerraba el menú
        if y >= self.H - TASK_H:
            self.on_taskbar(x, y)
            return
        w = self.win_at(x, y)
        if w is None:
            i = -1
            for j in range(len(self.icons)):
                if rin(self.icon_rect(j), x, y):
                    i = j
            if i != self.desk_sel:
                if self.desk_sel >= 0:
                    self.damage(self.icon_rect(self.desk_sel))
                self.desk_sel = i
                if i >= 0:
                    self.damage(self.icon_rect(i))
            last_t, last_o = self.last_click
            if i >= 0 and last_o == ("icon", i) and now - self.last_up < DOUBLE_MS:
                self.last_click = (0, None)
                self.icons[i][2]()
            else:
                self.last_click = (now, ("icon", i))
            return
        if w is not self.top():
            self.focus(w)
        for kind, r in w.title_btns():
            if rin(r, x, y):
                self.drag = ("button", w, kind, 0, None)
                return
        if y < w.y + TITLE_H:
            last_t, last_o = self.last_click
            if last_o == ("title", w) and now - self.last_up < DOUBLE_MS and w.resizable:
                self.last_click = (0, None)
                self.toggle_max(w)
                return
            self.last_click = (now, ("title", w))
            if not w.maximized:
                self.drag = ("move", w, x - w.x, y - w.y, None)
                self.snap = None
            return
        if w.resizable and not w.maximized and rin(w.grip(), x, y):
            self.drag = ("resize", w, x - w.w, y - w.h, None)
            return
        cx, cy, cw, ch = w.content()
        self.drag = ("content", w, 0, 0, None)
        w.mouse("down", x - cx, y - cy, b)
        last_t, last_o = self.last_click
        if last_o == ("content", w) and now - self.last_up < DOUBLE_MS:
            self.last_click = (0, None)
            w.mouse("double", x - cx, y - cy, b)
        else:
            self.last_click = (now, ("content", w))

    def on_drag(self, x, y, b):
        if self.drag is None:
            return
        mode, w = self.drag[0], self.drag[1]
        if mode == "move":
            if w.snapped and w.saved is not None:
                # al arrastrar una ventana encajada recupera su tamaño, bajo el puntero
                self.damage_box(w.rect())
                ow = w.w
                w.w, w.h = w.saved[2], w.saved[3]
                w.snapped = None
                fx = self.drag[2] * w.w // max(1, ow)
                self.drag = ("move", w, fx, self.drag[3], None)
                w.on_resize()
            zone = self.snap_zone(x, y) if w.resizable else None
            if zone != self.snap:
                if self.snap is not None:
                    self.damage_frame(self.snap_inner(self.snap), 3)
                self.snap = zone
                if zone is not None:
                    self.damage_frame(self.snap_inner(zone), 3)
            nx = min(max(x - self.drag[2], -w.w + 80), self.W - 80)
            ny = min(max(y - self.drag[3], 0), self.H - TASK_H - TITLE_H)
            if self.outline():
                self.set_ghost((nx, ny, w.w, w.h))
            elif (nx, ny) != (w.x, w.y):
                old = w.rect()
                w.x, w.y = nx, ny
                self.damage_move(old, w.rect())
        elif mode == "resize":
            nw = min(max(x - self.drag[2], w.min_w), self.W - w.x)
            nh = min(max(y - self.drag[3], w.min_h), self.H - TASK_H - w.y)
            if self.outline():
                self.set_ghost((w.x, w.y, nw, nh))
            elif (nw, nh) != (w.w, w.h):
                old = w.rect()
                w.w, w.h = nw, nh
                w.on_resize()
                self.damage_move(old, w.rect())
        elif mode == "content":
            cx, cy, cw, ch = w.content()
            w.mouse("drag", x - cx, y - cy, b)

    def on_up(self, x, y, b):
        self.last_up = self.ev_time
        d = self.drag
        self.drag = None
        if self.menu is not None and rin(self.menu.rect(), x, y):
            i = self.menu.item_at(x, y)
            if i >= 0:
                act = self.menu.items[i][2]
                self.close_menu()
                act()
            return
        if d is None:
            return
        mode, w = d[0], d[1]
        if self.ghost is not None and mode in ("move", "resize"):
            # modo contorno: la ventana se coloca al soltar, una sola vez
            gx, gy, gw, gh = self.ghost
            self.set_ghost(None)
            if (gx, gy, gw, gh) != w.rect():
                old = w.rect()
                resized = (gw, gh) != (w.w, w.h)
                w.x, w.y, w.w, w.h = gx, gy, gw, gh
                if resized:
                    w.on_resize()
                self.damage_move(old, w.rect())
        if mode == "button":
            for kind, r in w.title_btns():
                if kind == d[2] and rin(r, x, y):
                    if kind == "close":
                        self.close(w)
                    elif kind == "max":
                        self.toggle_max(w)
                    else:
                        self.minimize(w)
        elif mode == "content":
            cx, cy, cw, ch = w.content()
            w.mouse("up", x - cx, y - cy, b)
        elif mode == "move" and self.snap is not None:
            zone = self.snap
            self.damage_frame(self.snap_inner(zone), 3)
            self.snap = None
            if zone == "max":
                self.toggle_max(w)
            else:
                self.damage_box(w.rect())
                if not w.snapped:
                    w.saved = w.rect()
                w.x, w.y, w.w, w.h = self.snap_rect(zone)
                w.w -= SHADOW
                w.h -= SHADOW
                w.snapped = zone
                w.on_resize()
                self.damage_box(w.rect())

    # movimiento con contorno
    def outline(self):
        """Contorno al mover/redimensionar: en un framebuffer real (UEFI) mover el contenido
        obliga a volver a pintar la ventana entera en cada paso; el contorno cuesta 4 tiras."""
        m = SETTINGS.get("mover", "auto")
        if m == "auto":
            return self.info.get("adapter", "") != "framebuffer en memoria"
        return m == "contorno"

    def damage_frame(self, r, t):
        x, y, w, h = r
        self.damage((x, y, w, t))
        self.damage((x, y + h - t, w, t))
        self.damage((x, y + t, t, h - 2 * t))
        self.damage((x + w - t, y + t, t, h - 2 * t))

    def set_ghost(self, r):
        if r == self.ghost:
            return
        if self.ghost is not None:
            self.damage_frame(self.ghost, 3)
        self.ghost = r
        if r is not None:
            self.damage_frame(r, 3)

    def snap_inner(self, zone):
        sx, sy, sw, sh = self.snap_rect(zone)
        return (sx + 4, sy + 4, sw - 8, sh - 8)

    # encaje de ventanas en los bordes
    def snap_zone(self, x, y):
        if y <= 1:
            return "max"
        if x <= 1:
            return "left"
        if x >= self.W - 2:
            return "right"
        return None

    def snap_rect(self, zone):
        H = self.H - TASK_H
        half = self.W // 2
        if zone == "left":
            return (0, 0, half, H)
        if zone == "right":
            return (half, 0, self.W - half, H)
        return (0, 0, self.W, H)

    def on_right(self, x, y):
        if y >= self.H - TASK_H:
            for r, w in self.task_rects:
                if rin(r, x, y):
                    self.task_menu(w, x, y)
            return
        w = self.win_at(x, y)
        if w is None:
            self.open_menu(Menu(desktop_menu_items(self), x, y + Menu.ITEM_H * 6), "ctx")
            return
        if w is not self.top():
            self.focus(w)
        cx, cy, cw, ch = w.content()
        if rin((cx, cy, cw, ch), x, y):
            w.mouse("right", x - cx, y - cy, 2)

    def on_taskbar(self, x, y):
        if x < 100:
            self.open_menu(Menu(start_menu_items(self), 4, self.H - TASK_H), "start")
            return
        if x >= self.W - 120:
            c = self.find(Calendar)
            if c is not None and c is self.top():
                self.close(c)
            elif c is not None:
                self.focus(c)
            else:
                c = Calendar()
                self.add(c, self.W - c.w - 8, self.H - TASK_H - c.h - 6)
            return
        for r, w in self.task_rects:
            if rin(r, x, y):
                if w is self.top():
                    self.minimize(w)
                else:
                    self.focus(w)
                return
        if self.task_more is not None and rin(self.task_more[0], x, y):
            def pick(w):
                def f():
                    self.focus(w)
                return f
            items = [(clip_text(w.title, 300), w.icon if w.icon in ICONS else "app", pick(w))
                     for w in self.task_more[1]]
            m = Menu(items, x, self.H - TASK_H)
            m.x = min(x, self.W - m.w - SHADOW)
            self.open_menu(m, "ctx")
            return

    def handle_keys(self, data):
        for k in self.keys.feed(data):
            self.on_key(k)

    def on_key(self, k):
        if self.menu is not None:
            m = self.menu
            if k == "esc":
                self.close_menu()
            elif k == "down":
                m.move_sel(1)
                self.damage_box(m.body())
            elif k == "up":
                m.move_sel(-1)
                self.damage_box(m.body())
            elif k == "enter" and m.sel >= 0:
                act = m.items[m.sel][2]
                self.close_menu()
                act()
            elif printable(k):
                # una letra salta a la siguiente opción que empieza por ella
                n = len(m.items)
                for d in range(1, n + 1):
                    it = m.items[(m.sel + d) % n]
                    if it and it[0][:1].lower() == k.lower():
                        m.sel = (m.sel + d) % n
                        self.damage_box(m.body())
                        break
            return
        if k in ("super", "f1", "alt-m"):
            self.open_menu(Menu(start_menu_items(self), 4, self.H - TASK_H), "start")
            self.menu.move_sel(1)
            return
        if k == "alt-tab":
            vis = [w for w in self.wins]
            if len(vis) > 1:
                self.focus(vis[0])
            elif vis and vis[0].minimized:
                self.focus(vis[0])
            return
        if k == "alt-w" or k == "f4":
            t = self.top()
            if t is not None:
                self.close(t)
            return
        if k == "alt-t":
            self.icons[0][2]()
            return
        t = self.top()
        if t is not None:
            t.on_key(k)
            return
        n = len(self.icons)
        if k in ("down", "right", "tab") and n:
            self.select_icon((self.desk_sel + 1) % n)
        elif k in ("up", "left") and n:
            self.select_icon((self.desk_sel - 1) % n)
        elif k == "enter" and self.desk_sel >= 0:
            self.icons[self.desk_sel][2]()

    def select_icon(self, i):
        if self.desk_sel >= 0:
            self.damage(self.icon_rect(self.desk_sel))
        self.desk_sel = i
        self.damage(self.icon_rect(i))

    # ---------------------------------------------------------- bucle
    def tick(self):
        now = uptime_ms()
        busy = False
        for pid in list(REAP):
            try:
                got, st = waitpid(pid, True)
            except OSError:
                got = pid                      # ya no existe
            if got == pid:
                REAP.remove(pid)
        if REAP:
            busy = True
        for w in list(self.wins):
            try:
                if w.tick(now):
                    busy = True
            except Exception as e:
                self.broken.append((w, e, "en segundo plano"))
        if self.toasts and now >= self.toasts[0][1]:
            for i in range(len(self.toasts)):
                self.damage(self.toast_rect(i))
            self.toasts = [t for t in self.toasts if t[1] > now]
        if self.toasts:
            busy = True
        c = clock_str()
        if c != self.clock_text:
            self.damage((self.W - 120, self.H - TASK_H, 120, TASK_H))
        return busy

    t_start = None
    t_loaded = None

    def run(self):
        self.damage_all()
        busy = False
        first = True
        while self.running:
            self.flush()
            if first:
                first = False
                if self.t_start is not None:
                    now = uptime_ms()
                    try:
                        klog("escritorio listo en %d ms (carga y compilación %d ms, primer dibujo %d ms)" % (
                            now - self.t_start, self.t_loaded - self.t_start, now - self.t_loaded))
                    except OSError:
                        pass
            self.reap_broken()
            ev = gfx_poll(40 if busy or self.drag else 1000)
            try:
                if ev["mouse"]:
                    self.handle_mouse(ev["mouse"])
                if ev["keys"]:
                    self.handle_keys(ev["keys"])
            except Exception as e:
                # un fallo en una aplicación no tumba el escritorio
                self.drag = None
                self.report(self.top(), e, "al atender el ratón o el teclado", False)
            busy = self.tick()
            self.reap_broken()
        return self.exit_code

    def report(self, w, e, where, closed, name=None):
        name = w.title if w is not None else (name or "LOOK")
        text = "%s %s:\n%s" % (name, where, repr(e))
        tb = exc_traceback(e)
        place = ""
        if tb:
            f, line, fn = tb[0]
            place = "%s:%d en %s()" % (f.rsplit("/", 1)[-1], line, fn)
            text += "\n" + place
        try:
            log = "[%d] %s\n" % (uptime_ms(), text.replace("\n", " "))
            for f, line, fn in tb:
                log += "      %s:%d %s\n" % (f, line, fn)
            write_file("/var/log/look.log", log.encode(), True)
        except OSError:
            pass
        if closed:
            text += "\n\nLa ventana se ha cerrado. El resto del escritorio sigue funcionando."
        self.message("Error en una aplicación", text + "\n(registro: /var/log/look.log)")

    def reap_broken(self):
        while self.broken:
            w, e, where = self.broken.pop(0)
            if w in self.wins:
                self.damage_box(w.rect())
                self.wins.remove(w)
                try:
                    w.on_close()
                except Exception:
                    pass
                self.damage(self.taskbar_rect())
                self.report(w, e, where, True)


def resolve_clips(g):
    """Convierte clip_push/clip_pop (recorte de contenido de ventana) en 'clip' absolutos,
    intersecados con la región de daño en curso."""
    out = []
    region = None
    stack = []
    for c in g:
        op = c[0]
        if op == "clip":
            region = (c[1], c[2], c[3], c[4])
            stack = []
            out.append(c)
        elif op == "clip_push":
            cur = stack[-1] if stack else region
            r = rinter(cur, (c[1], c[2], c[3], c[4])) if cur is not None else (c[1], c[2], c[3], c[4])
            if r is None:
                r = (0, 0, 0, 0)
            stack.append(r)
            out.append(("clip",) + r)
        elif op == "clip_pop":
            if stack:
                stack.pop()
            cur = stack[-1] if stack else region
            if cur is None:
                out.append(("noclip",))
            else:
                out.append(("clip",) + cur)
        else:
            out.append(c)
    return out


def clock_str():
    # El reloj del firmware (RTC) suele ir en hora local; "tz" corrige en horas si no.
    try:
        off = int(SETTINGS.get("tz", "0"))
    except ValueError:
        off = 0
    s = (int(time()) + off * 3600) % 86400
    return "%02d:%02d" % (s // 3600, (s // 60) % 60)


# Logo "PyOS" en píxeles (letras de 5x7).
LOGO = [
    "####...........###....####",
    "#...#.........#...#..#....",
    "#...#.#...#...#...#..#....",
    "####..#...#...#...#...###.",
    "#.....#...#...#...#......#",
    "#......####...#...#......#",
    "#.........#....###...####.",
    ".......###................",
]
