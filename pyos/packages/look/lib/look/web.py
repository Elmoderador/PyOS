# /lib/look/web.py — Navegador de PyOS LOOK: HTTP/1.0 (pila TCP/IP de PyOS) + HTML básico.
include("/lib/http.py")

ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ", "copy": "©",
            "reg": "®", "aacute": "á", "eacute": "é", "iacute": "í", "oacute": "ó", "uacute": "ú",
            "ntilde": "ñ", "Ntilde": "Ñ", "uuml": "ü", "iexcl": "¡", "iquest": "¿", "middot": "·",
            "laquo": "«", "raquo": "»", "deg": "°", "mdash": "-", "ndash": "-", "hellip": "...",
            "euro": "EUR", "rsquo": "'", "lsquo": "'", "ldquo": '"', "rdquo": '"', "bull": "·"}
# bloques que separan párrafos (línea en blanco) y los que solo empiezan línea
PARA = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "pre", "blockquote", "hr",
        "section", "article", "header", "footer", "form", "dl")
LINE = ("div", "br", "li", "tr", "nav", "dt", "dd", "main", "aside", "figure")
BLOCK = PARA + LINE

HOME = """<html><head><title>Inicio</title></head><body>
<h1>Navegador de PyOS</h1>
<p>Este navegador habla HTTP/1.0 sobre la pila TCP/IP de PyOS (Python) y el driver
e1000 (Python). No hay TLS: solo direcciones <b>http://</b>.</p>
<h2>Prueba</h2>
<ul>
<li><a href="http://127.0.0.1/">http://127.0.0.1/</a> - el servidor web de este PyOS (svc start httpd)</li>
<li><a href="http://127.0.0.1/estado">http://127.0.0.1/estado</a> - estado del sistema</li>
<li><a href="http://neverssl.com/">http://neverssl.com/</a> - una web real sin https</li>
<li><a href="http://example.com/">http://example.com/</a></li>
</ul>
<p>Teclas: Ctrl+L dirección, RePág/AvPág desplazan, Retroceso vuelve atrás.</p>
</body></html>"""


def decode_entities(s):
    if "&" not in s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        j = s.find("&", i)
        if j < 0:
            out.append(s[i:])
            break
        out.append(s[i:j])
        k = s.find(";", j, j + 10)
        if k < 0:
            out.append("&")
            i = j + 1
            continue
        name = s[j + 1:k]
        if name.startswith("#"):
            try:
                cp = int(name[2:], 16) if name[1:2] in ("x", "X") else int(name[1:])
                out.append(chr(cp) if cp < 0x110000 else "?")
            except ValueError:
                out.append(s[j:k + 1])
        else:
            out.append(ENTITIES.get(name, s[j:k + 1]))
        i = k + 1
    return "".join(out)


def parse_html(html):
    """HTML -> (título, lista de (texto, estilo, enlace)) con '\\n' como saltos de bloque."""
    runs = []
    title = ""
    i = 0
    n = len(html)
    style = []
    href = None
    skip = 0
    pre = 0
    in_title = False
    while i < n:
        j = html.find("<", i)
        if j < 0:
            j = n
        if j > i and not skip:
            text = decode_entities(html[i:j])
            if in_title:
                title += text
            else:
                if not pre:
                    text = " ".join(text.split()) + (" " if text[-1:].isspace() else "")
                    if text[:1] == " " or html[i:i + 1].isspace():
                        text = " " + text.lstrip()
                if text.strip() or (pre and text):
                    runs.append((text, style[-1] if style else "", href))
        if j >= n:
            break
        k = html.find(">", j)
        if k < 0:
            break
        tag = html[j + 1:k].strip()
        i = k + 1
        if tag.startswith("!--"):
            e = html.find("-->", j)
            i = e + 3 if e >= 0 else n
            continue
        closing = tag.startswith("/")
        name = tag.lstrip("/").split()[0].lower().rstrip("/") if tag.lstrip("/") else ""
        if name in ("script", "style", "head") and name != "head":
            skip = skip + (-1 if closing else 1)
            skip = max(0, skip)
            continue
        if name == "title":
            in_title = not closing
            continue
        if name in BLOCK or name == "td" or name == "th":
            if name == "hr":
                runs.append(("\n\n", "", None))
                runs.append(("-" * 40, "muted", None))
            if name in ("td", "th"):
                runs.append(("  ", "", None))
            elif name == "br":
                runs.append(("\r", "", None))          # <br>: salto forzado, aunque la línea esté vacía
            else:
                runs.append(("\n\n" if name in PARA else "\n", "", None))
            if name == "li" and not closing:
                runs.append(("· ", "", None))
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if closing:
                if style:
                    style.pop()
            else:
                style.append("h1" if name in ("h1", "h2") else "h3")
        elif name in ("b", "strong", "th"):
            if closing:
                if style:
                    style.pop()
            else:
                style.append("b")
        elif name == "pre":
            pre = 0 if closing else 1
        elif name == "a":
            if closing:
                href = None
            else:
                p = tag.find("href=")
                if p >= 0:
                    v = tag[p + 5:].strip()
                    if v[:1] in ("'", '"'):
                        v = v[1:].split(v[0], 1)[0]
                    else:
                        v = v.split()[0] if v else ""
                    href = decode_entities(v)
        elif name == "img" and not closing:
            p = tag.find("alt=")
            alt = "imagen"
            if p >= 0:
                v = tag[p + 4:].strip()
                if v[:1] in ("'", '"'):
                    alt = v[1:].split(v[0], 1)[0] or alt
            runs.append(("[%s]" % alt, "muted", href))
    return " ".join(title.split()), runs


def layout(runs, cols):
    """Corta en líneas de `cols` caracteres: [[(col, texto, estilo, enlace)], ...]"""
    lines = [[]]
    col = 0
    for text, style, href in runs:
        if text == "\n":                              # empezar línea (si la actual tiene algo)
            if lines[-1]:
                lines.append([])
            col = 0
            continue
        if text == "\n\n":                            # párrafo: una línea en blanco, no más
            if lines[-1]:
                lines.append([])
            if len(lines) > 1 and lines[-2]:
                lines.append([])
            col = 0
            continue
        if text == "\r":                              # <br>
            lines.append([])
            col = 0
            continue
        parts = text.split("\n")
        for pi, part in enumerate(parts):
            if pi > 0:
                lines.append([])
                col = 0
            words = part.split(" ")
            for wi, w in enumerate(words):
                piece = w if wi == 0 else " " + w
                if col + len(piece) > cols and col > 0:
                    lines.append([])
                    col = 0
                    piece = piece.lstrip(" ")
                while len(piece) > cols:
                    lines[-1].append((col, piece[:cols - col], style, href))
                    piece = piece[cols - col:]
                    lines.append([])
                    col = 0
                if piece:
                    lines[-1].append((col, piece, style, href))
                    col += len(piece)
    return _trim(lines)


def _trim(lines):
    while len(lines) > 1 and not lines[0]:
        lines.pop(0)
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines


def join_url(base, href):
    if "://" in href or href.startswith("pyos:"):
        return href
    if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
        return None
    if base.startswith("file://"):
        if href.startswith("/"):
            return "file://" + href
        d = base[7:].rsplit("/", 1)[0]
        parts = []
        for seg in (d + "/" + href).split("/"):
            if seg == "..":
                if parts:
                    parts.pop()
            elif seg and seg != ".":
                parts.append(seg)
        return "file:///" + "/".join(parts)
    host, port, path = parse_url(base)
    root = "http://%s%s" % (host, ":%d" % port if port != 80 else "")
    if href.startswith("//"):
        return "http:" + href
    if href.startswith("/"):
        return root + href
    if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
        return None
    d = path.rsplit("/", 1)[0]
    parts = []
    for seg in (d + "/" + href).split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return root + "/" + "/".join(parts)


class Browser(Window):
    icon = "web"
    min_w = 420
    min_h = 260

    def __init__(self, url="pyos:inicio"):
        Window.__init__(self, "Navegador", 780, 540)
        self.url = url
        self.addr = url
        self.addr_cur = len(url)
        self.addr_focus = False
        self.history = []
        self.lines = []
        self.top_i = 0
        self.links = []
        self.status = ""
        self.page_title = ""
        self.runs = []
        self.cols = 80
        self.add_button(8, 8, 34, 28, "<", self.back)
        self.fd = None
        self.pid = None
        self.buf = bytearray()
        self.reload_btn = self.add_button(46, 8, 34, 28, "R", self.reload)
        self.go_btn = self.add_button(0, 8, 46, 28, "Ir", self.go, True)
        self.load(url, False)

    def on_resize(self):
        cx, cy, cw, ch = self.content()
        self.go_btn.r = (cw - 54, 8, 46, 28)
        cols = max(20, (cw - 40) // FW)
        if cols != self.cols:
            self.cols = cols
            self.lines = layout(self.runs, cols)

    def load(self, url, push=True):
        self.stop()
        if push and self.url and self.url != url:
            self.history.append(self.url)
        self.url = url
        self.addr = url
        self.addr_cur = len(url)
        self.top_i = 0
        if url == "pyos:inicio":
            self.show(HOME, "página interna")
        elif url.startswith("file://"):
            path = url[7:] or "/"
            try:
                data = read_file(path)
                ctype = "text/html" if path.endswith((".html", ".htm")) else "text/plain"
                self.show(self.to_html(data, ctype), "%s - %d bytes" % (path, len(data)))
            except OSError as e:
                self.show(self.error_page(url, e), "error: %s" % e)
        else:
            self.start_fetch(url)

    def start_fetch(self, url):
        r, w = pipe()
        try:
            self.pid = spawn("/lib/look/fetch.py", ["fetch", url], {1: w, 2: w}, "/")
        except OSError as e:
            close(r)
            close(w)
            self.show(self.error_page(url, e), "error: %s" % e)
            return
        close(w)
        set_nonblock(r)
        self.fd = r
        self.buf = bytearray()
        self.t0 = uptime_ms()
        self.got = 0
        self.status = "conectando con %s ..." % url
        self.reload_btn.label = "X"
        self.redraw()

    def stop(self, msg=None):
        if self.fd is None:
            return
        try:
            kill(self.pid, SIGKILL)
        except OSError:
            pass
        try:
            close(self.fd)
        except OSError:
            pass
        reap_later(self.pid)
        self.fd = self.pid = None
        self.reload_btn.label = "R"
        if msg:
            self.status = msg
            self.redraw()

    def tick(self, now):
        if self.fd is None:
            return False
        eof = False
        while True:
            try:
                d = read(self.fd, 16384)
            except OSError as e:
                if e.errno == EAGAIN:
                    break
                d = b""
            if not d:
                eof = True
                break
            self.buf += d
        # líneas de progreso
        while self.buf[:2] == b"P ":
            nl = self.buf.find(b"\n")
            if nl < 0:
                break
            try:
                self.got = int(self.buf[2:nl])
            except ValueError:
                pass
            del self.buf[:nl + 1]
        secs = (now - self.t0) / 1000.0
        st = "cargando %s ... %d KiB, %.0f s (Esc cancela)" % (self.url, self.got // 1024, secs)
        if st != self.status:
            self.status = st
            self.redraw()
        if not eof:
            return True
        close(self.fd)
        self.fd = None
        reap_later(self.pid)                   # ya cerró su salida: termina enseguida
        self.pid = None
        self.reload_btn.label = "R"
        data = bytes(self.buf)
        self.buf = bytearray()
        nl = data.find(b"\n")
        head = data[:nl].decode("utf-8", "replace") if nl >= 0 else data.decode("utf-8", "replace")
        if head.startswith("OK "):
            code_s, rest = head[3:].split(" ", 1)
            final, _, ctype = rest.partition("\t")
            body = data[nl + 1:]
            self.url = final
            self.addr = final
            self.addr_cur = len(final)
            self.show(self.to_html(body, ctype), "HTTP %s - %d bytes en %.1f s" % (code_s, len(body), secs))
            if self.wm is not None and self is not self.wm.top():
                self.wm.toast("Navegador: página cargada\n%s" % (self.page_title or final))
        else:
            err = head[4:] if head.startswith("ERR ") else (head or "el proceso de descarga terminó sin datos")
            self.show(self.error_page(self.url, err), "error: %s" % err)
        return False

    def to_html(self, body, ctype):
        cs = "utf-8"
        if "charset=" in ctype:
            cs = ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"')
        try:
            text = body.decode(cs, "replace")
        except LookupError:
            text = body.decode("utf-8", "replace")
        if "html" in ctype:
            return text
        return "<pre>" + text.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"

    def error_page(self, url, e):
        esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;")   # noqa: E731
        return ("<title>Error</title><h1>No se pudo cargar la página</h1><p>%s</p><p>%s</p>"
                "<p>Comprueba la red con <b>ifconfig</b> y <b>ping</b> en una terminal. Recuerda que "
                "https:// no está soportado.</p>" % (esc(url), esc(e)))

    def show(self, html, status):
        self.status = status
        self.page_title, self.runs = parse_html(html)
        self.lines = layout(self.runs, self.cols)
        self.top_i = 0
        self.title = "Navegador - " + (self.page_title or self.url)
        if self.wm is not None:
            self.wm.damage(self.wm.taskbar_rect())
        self.redraw()

    def on_close(self):
        self.stop()
        return True

    def back(self):
        if self.fd is not None:
            self.stop("cancelado")
        if self.history:
            self.load(self.history.pop(), False)

    def reload(self):
        if self.fd is not None:
            self.stop("cancelado")
        else:
            self.load(self.url, False)

    def go(self):
        u = self.addr.strip()
        if u.startswith("/"):
            u = "file://" + u
        elif u and "://" not in u and not u.startswith("pyos:"):
            u = "http://" + u
        self.addr_focus = False
        if u:
            self.load(u)

    def area(self):
        cx, cy, cw, ch = self.content()
        return (8, 44, cw - 16, ch - 44 - 28)

    def draw_content(self, g, x, y, w, h):
        d_field(g, x + 84, y + 8, w - 84 - 62, 28, self.addr, self.addr_focus,
                self.addr_cur if self.addr_focus else None)
        ax, ay, aw, ah = self.area()
        g.append(("rect", x + ax, y + ay, aw, ah, 0xFFFFFF))
        g.append(("frame", x + ax, y + ay, aw, ah, T["line"], 1))
        rows = max(1, (ah - 8) // FH)
        self.links = []
        for i in range(rows):
            j = self.top_i + i
            if j >= len(self.lines):
                break
            yy = y + ay + 4 + i * FH
            for col, text, style, href in self.lines[j]:
                xx = x + ax + 8 + col * FW
                if href:
                    g.append(("text", xx, yy, text, 0x1D4ED8, None))
                    g.append(("rect", xx, yy + FH - 3, FW * len(text), 1, 0x1D4ED8))
                    self.links.append(((ax + 8 + col * FW, ay + 4 + i * FH, FW * len(text), FH), href))
                elif style == "h1":
                    g.append(("text", xx, yy, text, 0x111827, None))
                    g.append(("text", xx + 1, yy, text, 0x111827, None))
                elif style == "h3" or style == "b":
                    g.append(("text", xx, yy, text, 0x1F2937, None))
                    g.append(("text", xx + 1, yy, text, 0x1F2937, None))
                elif style == "muted":
                    g.append(("text", xx, yy, text, 0x6B7280, None))
                else:
                    g.append(("text", xx, yy, text, 0x111827, None))
        d_scrollbar(g, x + ax + aw - 12, y + ay + 2, ah - 4, len(self.lines), rows, self.top_i)
        g.append(("text", x + 8, y + h - 22, clip_text(self.status, w - 16), T["muted"], None))

    def rows(self):
        ax, ay, aw, ah = self.area()
        return max(1, (ah - 8) // FH)

    def scroll(self, d):
        self.top_i = max(0, min(max(0, len(self.lines) - self.rows()), self.top_i + d))
        self.redraw()

    def on_mouse(self, kind, x, y, b):
        cx, cy, cw, ch = self.content()
        if kind == "down" and 84 <= x < cw - 62 and 8 <= y < 36:
            self.addr_focus = True
            self.addr_cur = len(self.addr)
            self.redraw()
            return
        if kind == "down":
            if self.addr_focus:
                self.addr_focus = False
                self.redraw()
            for r, href in self.links:
                if rin(r, x, y):
                    if self.url.startswith("pyos:"):
                        u = href if "://" in href else None
                    else:
                        u = join_url(self.url, href)
                    if u:
                        self.load(u)
                    return
        elif kind == "wheel":
            self.scroll(3 * b)

    def on_key(self, k):
        if self.addr_focus:
            if k == "enter":
                self.go()
            elif k == "esc":
                self.addr_focus = False
                self.addr = self.url
            elif k == "backspace" and self.addr_cur > 0:
                self.addr = self.addr[:self.addr_cur - 1] + self.addr[self.addr_cur:]
                self.addr_cur -= 1
            elif k == "left":
                self.addr_cur = max(0, self.addr_cur - 1)
            elif k == "right":
                self.addr_cur = min(len(self.addr), self.addr_cur + 1)
            elif k == "home":
                self.addr_cur = 0
            elif k == "end":
                self.addr_cur = len(self.addr)
            elif k == "ctrl-v":
                t = clip_get().split("\n")[0].strip()
                self.addr = self.addr[:self.addr_cur] + t + self.addr[self.addr_cur:]
                self.addr_cur += len(t)
            elif k == "ctrl-c":
                clip_set(self.addr)
            elif printable(k):
                self.addr = self.addr[:self.addr_cur] + k + self.addr[self.addr_cur:]
                self.addr_cur += 1
            self.redraw()
            return
        if k == "esc" and self.fd is not None:
            self.stop("cancelado")
        elif k == "ctrl-l" or k == "f6":
            self.addr_focus = True
            self.addr = ""
            self.addr_cur = 0
            self.redraw()
        elif k in ("pgdn", " "):
            self.scroll(self.rows() - 2)
        elif k == "pgup":
            self.scroll(-(self.rows() - 2))
        elif k == "down":
            self.scroll(1)
        elif k == "up":
            self.scroll(-1)
        elif k == "home":
            self.scroll(-len(self.lines))
        elif k == "end":
            self.scroll(len(self.lines))
        elif k == "backspace":
            self.back()
        elif k == "f5":
            self.reload()
        elif k == "ctrl-c":
            clip_set(self.url)
