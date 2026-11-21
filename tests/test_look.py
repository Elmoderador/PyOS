"""PyOS LOOK de punta a punta en la máquina emulada (framebuffer en memoria + ratón PS/2
simulado con paquetes reales). Las capturas se guardan en tests/out/ para revisarlas."""
import os
import time

import pytest

from pyos.__main__ import run_machine
from pyos.hal.emulated import ScriptConsole
from pyos.tools import mkimage
from tests.lookdriver import LookSession

OUT = os.path.join(os.path.dirname(__file__), "out")
W, H = 1024, 768
TASK_Y = H - 17
ICON = lambda i: (52, 52 + 88 * i)     # noqa: E731  (columna de iconos del escritorio)


@pytest.fixture
def image(tmp_path):
    p = str(tmp_path / "pyos.img")
    mkimage.build(p, size_mb=16)
    return p


def save(sess, name):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + ".png"), "wb") as f:
        f.write(sess.png(name))


def menu_pick(s, ups):
    s.click(44, TASK_Y)
    s.keys(b"\x1b[A" * ups + b"\r", 0.8)


def exit_look(s):
    menu_pick(s, 2)                       # "Salir a PyOS Term"


def term_run(image, steps):
    con = ScriptConsole(steps, timeout=30)
    run_machine(image, 16 << 20, lambda: con, max_reboots=1)
    return con.transcript


def test_escritorio_ventanas_y_terminal(image):
    S = LookSession(image)

    def script(s):
        s.shot("escritorio")
        s.click(*ICON(0), double=True)                 # Terminal
        s.keys(b"echo desde-look > /root/look.txt\r", 1.5)
        s.shot("terminal")
        s.drag(500, 74, 400, 200)                       # mover la ventana por el título
        s.shot("movida")
        exit_look(s)
    S.after = ["cat /root/look.txt", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    # escritorio: barra de tareas abajo, botón PyOS verde
    esc = S.shots["escritorio"]
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    assert px(esc, 90, H - 8) == 0x10B981             # botón "PyOS"
    assert px(esc, 600, 5) != px(esc, 600, 600)         # fondo en degradado
    # la ventana se movió: su barra de título está ahora más abajo
    mov = S.shots["movida"]
    assert px(mov, 420, 205) != px(S.shots["terminal"], 420, 205)
    assert "has salido de PyOS LOOK" in t
    assert "desde-look" in t.split("cat /root/look.txt")[1]


def test_archivos_notas_y_ajustes(image):
    S = LookSession(image)
    # Posiciones según la colocación de WM.add para la primera ventana abierta:
    # x = (W - ancho) // 2 - 60, y = (H - 34 - alto) // 2 - 60; contenido en (x+1, y+26).
    fx, fy = (W - 660) // 2 - 60, (H - 34 - 460) // 2 - 60      # Archivos 660x460
    sx, sy = (W - 700) // 2 - 60, (H - 34 - 480) // 2 - 60      # Ajustes 700x480

    def script(s):
        s.click(*ICON(1), double=True)                          # Archivos (/root)
        s.shot("archivos")
        s.click(fx + 1 + 160 + 60, fy + 26 + 8 + 14)             # botón "Nueva carpeta"
        s.keys(b"proyectos\r", 0.8)
        s.shot("carpeta")
        s.keys(b"\x1bw", 0.5)                                    # Alt+W cierra la ventana activa
        s.click(*ICON(2), double=True)                          # Notas
        s.keys(b"Hola desde Notas\rlinea 2\x13", 0.8)            # Ctrl+S -> "Guardar como"
        s.keys(b"\x7f" * 20 + b"/root/nota.txt\r", 1.0)
        s.shot("notas")
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(5), double=True)                          # Ajustes
        s.shot("ajustes")
        s.click(sx + 1 + 170 + 128 + 60, sy + 26 + 100)          # segundo tema: "Bosque"
        s.shot("tema")
        exit_look(s)
    S.after = ["ls /root", "cat /root/nota.txt", "cat /etc/look.conf", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    assert "proyectos" in tail
    assert "Hola desde Notas\nlinea 2" in tail
    assert "theme=bosque" in tail


def test_juegos_en_un_terminal_de_look_y_el_teclado_vuelve(image):
    S = LookSession(image)

    def script(s):
        s.click(*ICON(6), double=True)                 # Juegos: centro de juegos
        gx, gy = (W - 460) // 2 - 60 + 1, (H - 34 - 300) // 2 - 60 + 26
        s.click(gx + 230, gy + 135)                     # "Arcade": arcade dentro de un terminal
        time.sleep(1.5)
        s.shot("arcade")
        s.keys(b"q", 1.5)                               # sale de arcade (que tenía el teclado)
        s.keys(b"\r", 0.8)                              # cierra el terminal terminado
        s.click(*ICON(0), double=True)
        s.keys(b"echo teclado-de-vuelta > /root/k.txt\r", 1.2)
        exit_look(s)
    S.after = ["cat /root/k.txt", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    save(S, "arcade")
    assert "teclado-de-vuelta" in t.split("has salido de PyOS LOOK")[1]


def test_look_desinstalado_cae_a_term(image):
    term_run(image, ["pkg remove look", "halt"])
    con = ScriptConsole(["halt"], timeout=20)
    run_machine(image, 16 << 20, lambda: con, max_reboots=1, mode="look")
    assert "PyOS LOOK no está instalado" in con.transcript
    assert "pkg install look" in con.transcript


def test_pantalla_exclusiva_y_permisos(image):
    t = term_run(image, [
        "python -c gfx_draw([('rect',0,0,5,5,0)])",
        "python -c print(gfx_poll(0))",
        "cat /proc/gfx",
        "halt"])
    assert t.count("Operation not permitted") + t.count("PermissionError") >= 2
    assert "gfx: libre" in t


def test_navegador_contra_el_httpd_local(image):
    S = LookSession(image)
    bx, by = (W - 780) // 2 - 60, (H - 34 - 540) // 2 - 60         # Navegador 780x540

    def script(s):
        s.click(*ICON(0), double=True)                              # terminal: arrancar httpd
        s.keys(b"svc start httpd\r", 2.0)
        s.keys(b"\x1bw", 0.5)
        s.click(52 + 88, 52, double=True)                           # Navegador (2ª columna)
        time.sleep(1.0)
        s.shot("navegador")
        s.keys(b"\x0c", 0.3)                                        # Ctrl+L: barra de dirección
        s.keys(b"127.0.0.1/\r", 4.0)
        s.shot("web")
        s.keys(b"\x7f", 2.0)                                        # Retroceso: atrás
        s.shot("atras")
        exit_look(s)
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    # área de página blanca dentro de la ventana
    assert px(S.shots["web"], bx + 1 + 20, by + 26 + 44 + 200) == 0xFFFFFF
    assert S.shots["web"] != S.shots["navegador"]
    assert "has salido de PyOS LOOK" in t


def test_html_parser_y_maquetado():
    import builtins
    src = open(os.path.join(os.path.dirname(__file__), "..", "pyos", "packages", "look", "lib",
                            "look", "web.py"), encoding="utf-8").read()
    ns = {"include": lambda p: None, "Window": object,
          "parse_url": lambda u: (u.split("/")[2].split(":")[0],
                                  int(u.split("/")[2].split(":")[1]) if ":" in u.split("/")[2] else 80,
                                  "/" + u.split("/", 3)[3] if u.count("/") >= 3 else "/")}
    exec(compile(src, "web.py", "exec"), ns)
    title, runs = ns["parse_html"]("<html><head><title> Hola  &amp; adiós </title><style>x{}</style>"
                                   "</head><body><h1>Tí&iacute;tulo</h1><p>uno <a href='/b'>dos</a>"
                                   "&#33;</p><script>alert(1)</script><ul><li>x</li></ul></body>")
    assert title == "Hola & adiós"
    text = "".join(r[0] for r in runs)
    assert "Tíítulo" in text and "alert" not in text and "x{}" not in text and "!" in text
    assert any(r[2] == "/b" and "dos" in r[0] for r in runs)
    lines = ns["layout"]([("palabra " * 30, "", None)], 20)
    assert all(sum(len(p[1]) for p in l) <= 20 for l in lines)
    ju = ns["join_url"]
    assert ju("http://h/a/b.html", "c.html") == "http://h/a/c.html"
    assert ju("http://h/a/b.html", "../x") == "http://h/x"
    assert ju("http://h:8080/a/", "/r") == "http://h:8080/r"
    assert ju("http://h/a", "http://o/") == "http://o/"
    assert ju("http://h/a", "#top") is None


# ---------------------------------------------------------------- ronda 2: rueda, Paint, visor, calculadora
LOOKLIB = os.path.join(os.path.dirname(__file__), "..", "pyos", "packages", "look", "lib", "look")


def _look_ns():
    """apps2.py + image.py en el host con sustitutos mínimos de libpy/core."""
    files = {}

    class Win(object):
        def __init__(self, *a, **k):
            self.buttons = []
            self.wm = None

        def add_button(self, *a):
            pass

        def redraw(self):
            pass

    ns = {"Window": Win, "read_file": lambda p: files[p], "T": {}, "FW": 8, "FH": 19,
          "write_file": lambda p, d, append=False: files.__setitem__(p, bytes(d)),
          "uptime_ms": lambda: 0}
    ns["include"] = lambda p: exec(compile(open(os.path.join(LOOKLIB, p.rsplit("/", 1)[1]),
                                                encoding="utf-8").read(), p, "exec"), ns)
    ns["include"]("/lib/look/apps2.py")
    return ns, files


def test_calculadora_y_libreria_de_imagenes():
    ns, files = _look_ns()
    ev, fmt = ns["calc_eval"], ns["calc_fmt"]
    assert fmt(ev("2+3*4")) == "14"
    assert fmt(ev("(2+3)*4")) == "20"
    assert fmt(ev("-2^2")) == "-4" and fmt(ev("2^3^2")) == "512"
    assert fmt(ev("7/2")) == "3.5" and fmt(ev("10%4")) == "2" and fmt(ev("1,5×2")) == "3"
    for bad in ("1/0", "2+", "(1", "abc", ""):
        with pytest.raises(ns["CalcError"]):
            ev(bad)
    # BMP: escribir y releer (24 bits, ancho impar para el relleno de fila)
    w, h = 5, 3
    px = bytearray(range(45))
    ns["save_bmp"]("/t.bmp", w, h, px)
    assert ns["load"]("/t.bmp") == (w, h, px)
    # las muestras del paquete se leen (8 bits con paleta, 24 bits, PPM)
    d = os.path.join(os.path.dirname(__file__), "..", "pyos", "packages", "look", "usr", "share", "images")
    for n, size in (("serpiente.bmp", (128, 128)), ("paisaje.bmp", (320, 200)), ("colores.ppm", (256, 96))):
        data = open(os.path.join(d, n), "rb").read()
        img = ns["load_bmp"](data) if n.endswith(".bmp") else ns["load_pnm"](data)
        assert img[:2] == size and len(img[2]) == 3 * size[0] * size[1]
    sw, sh, sp = ns["shrink"](4, 2, bytearray(range(24)), 2)
    assert (sw, sh, bytes(sp)) == (2, 1, bytes([0, 1, 2, 6, 7, 8]))


def test_cubo_de_pintura():
    ns, files = _look_ns()
    p = ns["Paint"]()
    p.cw, p.chh = 40, 30
    p.px = bytearray(b"\xff" * (3 * 40 * 30))
    p.rect_outline(5, 5, 30, 20, 1, b"\x00\x00\x00")          # caja cerrada
    bb = p.flood(10, 10, b"\x00\x00\xff")
    assert bb == [6, 6, 29, 19]
    at = lambda x, y: bytes(p.px[(y * 40 + x) * 3:(y * 40 + x) * 3 + 3])   # noqa: E731
    assert at(10, 10) == b"\x00\x00\xff" and at(29, 19) == b"\x00\x00\xff"
    assert at(2, 2) == b"\xff\xff\xff" and at(5, 5) == b"\x00\x00\x00"
    assert p.flood(1, 1, b"\xff\xff\xff") is None              # mismo color: nada


def test_rueda_paint_y_visor(image):
    S = LookSession(image)
    ICON2 = lambda i: (52 + 88, 52 + 88 * i)          # noqa: E731  (segunda columna)

    def script(s):
        # rueda sobre el menú de inicio: baja a "Terminal" e Intro la abre
        s.click(44, TASK_Y)
        s.machine.mouse.scroll(1)
        time.sleep(0.6)
        s.keys(b"\r", 1.2)
        s.keys(b"echo rueda-ok > /root/r.txt\r", 1.2)
        s.keys(b"\x1bw", 0.5)
        # Paint: un trazo y Ctrl+S
        s.click(*ICON2(1), double=True)
        time.sleep(1.0)
        s.drag(300, 250, 420, 300)
        s.shot("paint")
        s.keys(b"\x13", 0.8)
        s.keys(b"\x7f" * 40 + b"/root/trazo.bmp\r", 1.5)
        s.keys(b"\x1bw", 0.5)
        # visor de imágenes con el paisaje de ejemplo
        s.click(*ICON2(2), double=True)
        time.sleep(2.0)
        s.shot("visor")
        exit_look(s)
    S.after = ["cat /root/r.txt", "ls /root", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    assert "rueda-ok" in tail
    assert "trazo.bmp" in tail
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    assert px(S.shots["paint"], 420, 275) == 0x000000           # el trazo está en el lienzo
    # visor: centro del área de imagen = cielo/montañas del paisaje, no el fondo gris
    vx, vy = (W - 720) // 2 - 60 + 1, (H - 34 - 540) // 2 - 60 + 26
    c = px(S.shots["visor"], vx + 359, vy + 44 + 100)
    assert c != 0x1F2937


def test_encajar_ventanas_en_los_bordes(image):
    S = LookSession(image)

    def script(s):
        s.click(*ICON(7), double=True)                 # Acerca de (no redimensionable: no encaja)
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(0), double=True)                 # Terminal
        tx, ty = (W - 688) // 2 - 60, (H - 34 - 491) // 2 - 60     # Terminal 688x491
        s.goto(tx + 200, ty + 10)
        s.machine.mouse.set_buttons(1)
        time.sleep(0.05)
        s.machine.mouse.move(-1000, 0)                 # al borde izquierdo
        time.sleep(0.4)
        s.shot("encaje_previa")
        s.machine.mouse.set_buttons(0)
        time.sleep(0.6)
        s.shot("encajada")
        exit_look(s)
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    enc = S.shots["encajada"]
    # la ventana ocupa la mitad izquierda: su borde derecho está en x = W/2 - SHADOW
    pre = S.shots["encaje_previa"]
    assert any(px(pre, x, 300) != px(enc, x, 300) for x in range(4, 10))   # marco de previsualización
    assert px(enc, W // 2 + 40, 300) != px(enc, 300, 300)    # derecha: escritorio; izquierda: terminal
    assert px(enc, 300, 300) == px(enc, 300, H - 80)          # la terminal llega hasta abajo


def test_apps_de_terceros_y_fallos_aislados(image):
    term_run(image, [
        "echo \"LOOK_APPS.append(('Boom', 'app', lambda: 1 // 0))\" > /usr/share/look/apps/boom.py",
        "echo \"def (\" > /usr/share/look/apps/roto.py",
        "halt"])
    S = LookSession(image)

    def script(s):
        time.sleep(0.8)
        s.shot("plugins_error")
        s.keys(b"\r", 0.6)                             # cierra el aviso de plugins rotos
        menu_pick(s, 9)                                 # "Boom": revienta al abrirse (el separador no cuenta)
        time.sleep(0.5)
        s.shot("boom")
        s.keys(b"\r", 0.6)                             # cierra el diálogo de error
        menu_pick(s, 8)                                 # "Reloj" (la app de ejemplo)
        time.sleep(1.0)
        s.shot("reloj")
        s.keys(b" ", 1.2)                               # arranca el cronómetro
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(0), double=True)                  # LOOK sigue vivo
        s.keys(b"echo sigo-vivo > /root/v.txt\r", 1.2)
        exit_look(s)
    S.after = ["cat /root/v.txt", "cat /var/log/look.log", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    assert "sigo-vivo" in tail
    assert "Boom al abrirse" in tail and "ZeroDivisionError" in tail
    assert S.shots["boom"] != S.shots["plugins_error"]


def test_buscaminas_y_serpiente(image):
    S = LookSession(image)
    gx, gy = (W - 460) // 2 - 60 + 1, (H - 34 - 300) // 2 - 60 + 26          # Juegos 460x300
    mw, mh = 16 * 24 + 18, 16 * 24 + 48 + 8 + 27                            # Buscaminas medio
    mx, my = (W - mw) // 2 + 24 - 60 + 1, (H - 34 - mh) // 2 + 24 - 60 + 26  # 2ª ventana

    def script(s):
        s.click(*ICON(6), double=True)
        s.click(gx + 120, gy + 55)                      # Buscaminas
        time.sleep(0.8)
        s.shot("minas0")
        s.click(mx + 8 + 8 * 24 + 12, my + 48 + 8 * 24 + 12)    # primer clic: siempre seguro
        time.sleep(0.8)
        s.click(mx + 8 + 15 * 24 + 12, my + 48 + 0 * 24 + 12, button=2)   # bandera (si sigue tapada)
        time.sleep(0.5)
        s.shot("minas")
        s.keys(b"\x1bw", 0.5)
        s.click(gx + 340, gy + 55)                      # Serpiente
        time.sleep(0.8)
        s.keys(b"\x1b[C", 1.5)                         # derecha: empieza
        s.keys(b"\x1b[B", 1.0)                         # abajo
        s.shot("serpiente")
        exit_look(s)
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    # la casilla del primer clic está destapada (0 minas alrededor: gris claro)
    assert px(S.shots["minas"], mx + 8 + 8 * 24 + 12, my + 48 + 8 * 24 + 12) == 0xE5E7EB
    assert px(S.shots["minas0"], mx + 8 + 8 * 24 + 12, my + 48 + 8 * 24 + 12) == 0xB8C0CC
    assert "has salido de PyOS LOOK" in t


def test_portapapeles_notas_y_terminal(image):
    S = LookSession(image)
    nx, ny = (W - 640) // 2 - 60 + 1, (H - 34 - 460) // 2 - 60 + 26      # Notas, 1ª ventana

    def script(s):
        s.click(*ICON(2), double=True)                                  # Notas
        s.keys(b"hola mundo\rsegunda linea", 0.6)
        s.keys(b"\x01\x03", 0.4)                                        # Ctrl+A, Ctrl+C
        s.keys(b"\x1b[F\r", 0.3)                                        # Fin, Intro
        s.keys(b"\x16", 0.6)                                            # Ctrl+V
        s.keys(b"\x06", 0.5)                                            # Ctrl+F: buscar
        s.keys(b"segunda\r", 0.6)
        s.keys(b"\x18", 0.4)                                            # Ctrl+X corta "segunda"
        s.keys(b"\x13", 0.6)                                            # Ctrl+S -> guardar como
        s.keys(b"\x7f" * 20 + b"/root/clip.txt\r", 1.0)
        s.shot("notas_clip")
        # doble clic en "mundo" (línea 1) y pegar en la terminal con el botón derecho
        s.click(nx + 8 + 40 + 7 * FW8, ny + 44 + 4 + 5, double=True)
        s.keys(b"\x03", 0.4)
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(0), double=True)
        s.keys(b"echo ", 0.4)
        s.click(500, 300, button=2)
        s.keys(b" > /root/pegado.txt\r", 1.2)
        s.shot("term_pegado")
        s.keys(b"sleep 60\r", 1.0)                                    # Ctrl+C interrumpe el programa
        s.keys(b"\x03", 1.0)
        s.keys(b"echo interrumpido > /root/i.txt\r", 1.2)
        exit_look(s)
    S.after = ["cat /root/clip.txt", "cat /root/pegado.txt", "cat /root/i.txt", "cat /var/log/look.log", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    # tras Ctrl+X la primera "segunda" (la original) ha desaparecido; la pegada sigue
    assert "hola mundo\n linea\nhola mundo\nsegunda linea" in tail
    assert tail.split("cat /root/pegado.txt")[1].lstrip().startswith("mundo")
    assert "interrumpido" in tail.split("cat /root/i.txt")[1]


FW8 = 8


def test_archivos_copiar_pegar_y_borrar_recursivo(image):
    term_run(image, ["mkdir /root/a", "echo dentro > /root/a/b.txt", "halt"])
    S = LookSession(image)
    fx, fy = (W - 660) // 2 - 60 + 1, (H - 34 - 460) // 2 - 60 + 26

    def script(s):
        s.click(*ICON(1), double=True)                  # Archivos en /root: "a" es la fila 0
        time.sleep(0.6)
        s.keys(b"\x03", 0.4)                            # Ctrl+C
        s.keys(b"\x16", 1.0)                            # Ctrl+V -> "a (2)"
        s.click(fx + 100, fy + 80 + 11, button=2)       # menú contextual sobre "a"
        time.sleep(0.4)
        s.shot("archivos_menu")
        s.keys(b"\x1b[B" * 6 + b"\r", 0.6)               # ... "Borrar"
        s.shot("archivos_borrar")
        s.keys(b"\x1b[D\r", 1.0)                        # foco en Cancelar: flecha izq. -> "Borrar"
        exit_look(s)
    S.after = ["ls /root", "cat \"/root/a (2)/b.txt\"", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    ls = tail.split("ls /root")[1].split("root@pyos")[0]
    assert "a (2)" in ls and "\na\n" not in ls
    assert "dentro" in tail.split("b.txt\"")[1]


def test_fondo_calendario_y_menu_de_tareas(image):
    S = LookSession(image)
    sx, sy = (W - 700) // 2 - 60 + 1, (H - 34 - 480) // 2 - 60 + 26          # Ajustes

    def script(s):
        s.click(*ICON(5), double=True)                  # Ajustes > Apariencia
        time.sleep(0.6)
        s.click(sx + 170 + 106 + 50, sy + 226 + 15)       # 1ª imagen de /usr/share/images (paisaje)
        time.sleep(1.5)
        s.keys(b"\x1bw", 0.6)
        s.shot("fondo")
        s.click(W - 60, TASK_Y)                         # reloj -> calendario
        time.sleep(0.8)
        s.shot("calendario")
        s.click(W - 60, TASK_Y)                         # otra vez: se cierra
        s.click(*ICON(0), double=True)
        s.click(200, TASK_Y, button=2)                  # menú de la tarea "Terminal"
        time.sleep(0.4)
        s.keys(b"\x1b[B\r", 0.6)                         # "Minimizar"
        s.shot("minimizada")
        s.click(44, TASK_Y)                             # menú PyOS + letra: "c" -> Calculadora
        s.keys(b"c\r", 1.0)
        s.shot("letra")
        exit_look(s)
    S.after = ["cat /etc/look.conf", "cat /var/log/look.log", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    assert "wallpaper=/usr/share/images/paisaje.bmp" in tail
    assert "No such file" in tail.split("cat /var/log/look.log")[1].split("root@pyos")[0]   # ningún fallo
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    # paisaje x4 centrado: la franja de cielo más alta (0x0B1E3F) arriba en el centro
    assert px(S.shots["fondo"], 600, 2) == 0x0B1E3F
    assert px(S.shots["calendario"], W - 200, H - 200) != px(S.shots["fondo"], W - 200, H - 200)
    assert S.shots["letra"] != S.shots["minimizada"]


def test_ayuda_y_avisos(image):
    term_run(image, ["echo x > /root/f.txt", "halt"])
    S = LookSession(image)

    def script(s):
        menu_pick(s, 4)                                 # "Ayuda"
        time.sleep(0.6)
        s.shot("ayuda")
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(1), double=True)                  # Archivos: copiar y pegar -> aviso
        time.sleep(0.5)
        s.keys(b"\x03\x16", 1.0)
        s.shot("aviso")
        time.sleep(4.5)                                 # el aviso desaparece solo
        s.shot("sin_aviso")
        exit_look(s)
    S.after = ["ls /root", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    assert "f (2).txt" in t.split("has salido de PyOS LOOK")[1]
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    tx, ty = W - 340 - 10 + 2, H - 34 - 10 - 50 + 20        # barra de color del aviso
    assert px(S.shots["aviso"], tx, ty) != px(S.shots["sin_aviso"], tx, ty)
    assert S.shots["ayuda"] != S.shots["aviso"]


def test_dialogo_con_teclado_y_tema_contraste(image):
    term_run(image, ["echo x > /root/borrame.txt", "halt"])
    S = LookSession(image)
    sx, sy = (W - 700) // 2 - 60 + 1, (H - 34 - 480) // 2 - 60 + 26

    def script(s):
        s.click(*ICON(1), double=True)                 # Archivos: Supr -> "¿Borrar...?"
        time.sleep(0.5)
        s.keys(b"\x1b[3~", 0.6)
        s.keys(b"\t", 0.4)                             # foco a "Cancelar"
        s.shot("dialogo_foco")
        s.keys(b"\r", 0.6)                             # Intro = Cancelar: no se borra
        s.keys(b"\x1bw", 0.5)
        s.click(*ICON(5), double=True)                 # Ajustes: tema de alto contraste
        time.sleep(0.5)
        s.click(sx + 170 + 2 * 128 + 60, sy + 100)
        time.sleep(1.0)
        s.shot("contraste")
        exit_look(s)
    S.after = ["ls /root", "cat /etc/look.conf", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    tail = t.split("has salido de PyOS LOOK")[1]
    assert "borrame.txt" in tail and "theme=contraste" in tail


def test_listas_vacias_y_traza_en_el_registro(image):
    # regresión (fuzzer a 800x600): flecha abajo en una carpeta vacía dejaba sel = -1 y el
    # dibujo de Archivos saltaba con IndexError
    S = LookSession(image, size=(800, 600))
    term_run(image, ["echo \"LOOK_APPS.append(('Boom', 'app', lambda: [][3]))\" > /usr/share/look/apps/boom.py",
                     "halt"])

    def script(s):
        s.click(52, 140, double=True)                   # Archivos en /root (vacía)
        time.sleep(0.5)
        s.keys(b"\x1b[B\x1b[B\x1b[6~\x1b[5~\x1b[A", 0.8)
        s.goto(300, 300)
        s.machine.mouse.scroll(3)
        time.sleep(0.5)
        s.shot("vacia")
        s.keys(b"\x1bw", 0.4)
        s.click(44, 600 - 17)                           # Boom (encima de Ayuda, Acerca de... )
        s.keys(b"\x1b[A" * 9 + b"\r", 0.8)
        s.keys(b"\r", 0.4)
        s.click(44, 600 - 17)
        s.keys(b"\x1b[A\x1b[A\r", 1.5)
    S.after = ["cat /var/log/look.log", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    save(S, "vacia")
    log = t.split("cat /var/log/look.log")[1].split("root@pyos")[0]
    assert "Archivos" not in log                         # ningún fallo de Archivos
    assert "IndexError" in log and "boom.py:1" in log     # la traza dice dónde falló Boom


def test_resaltado_al_pasar_por_un_boton(image):
    S = LookSession(image)
    gx, gy = (W - 460) // 2 - 60 + 1, (H - 34 - 300) // 2 - 60 + 26          # Juegos

    def script(s):
        s.click(*ICON(6), double=True)
        time.sleep(0.6)
        s.goto(gx + 230, gy + 200)                       # fuera de los botones
        time.sleep(0.4)
        s.shot("sin_hover")
        s.goto(gx + 230, gy + 120)                       # sobre "Arcade (8 juegos...)"
        time.sleep(0.4)
        s.shot("hover")
        exit_look(s)
    S.run(script)
    assert not S.errors, S.errors
    px = lambda frame, x, y: frame[(y * W + x) * 4 + 2] << 16 | frame[(y * W + x) * 4 + 1] << 8 | frame[(y * W + x) * 4]  # noqa
    # el fondo del botón cambia al pasar por encima (lejos del cursor y del texto)
    assert px(S.shots["hover"], gx + 30, gy + 112) != px(S.shots["sin_hover"], gx + 30, gy + 112)


def test_notas_pregunta_antes_de_perder_cambios(image):
    S = LookSession(image)

    def script(s):
        s.click(*ICON(2), double=True)
        s.keys(b"texto importante", 0.5)
        s.keys(b"\x1bw", 0.6)                            # cerrar: pregunta
        s.shot("pregunta")
        s.keys(b"\r", 0.6)                               # "Guardar" -> pide ruta
        s.keys(b"\x7f" * 20 + b"/root/importante.txt\r", 1.0)
        s.shot("cerrada")
        s.click(*ICON(2), double=True)                   # otra nota sin guardar...
        s.keys(b"borrador", 0.5)
        s.click(44, TASK_Y)                              # ...y salir de LOOK: avisa
        s.keys(b"\x1b[A\x1b[A\r", 0.8)
        s.shot("aviso_salir")
        s.keys(b"\r", 0.6)                               # foco en "Cancelar" (lo seguro): no sale
        s.shot("sigue")
        s.click(44, TASK_Y)
        s.keys(b"\x1b[A\x1b[A\r", 0.8)
        s.keys(b"\x1b[D\r", 1.5)                         # flecha izquierda -> "Salir"
    S.after = ["cat /root/importante.txt", "halt"]
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    assert "texto importante" in t.split("cat /root/importante.txt")[1]
    assert "has salido de PyOS LOOK" in t
    assert S.shots["pregunta"] != S.shots["cerrada"]


def test_barra_con_muchas_ventanas(image):
    S = LookSession(image, size=(800, 600))

    def script(s):
        for _ in range(11):                              # 11 calculadoras: no caben en 800 px
            s.click(44, 600 - 17)
            s.keys(b"c\r", 0.6)
        s.shot("muchas")
        s.click(104 + 8 * 64 + 22, 600 - 17)             # el botón "+N" (tras 8 botones de 60 px)
        time.sleep(0.5)
        s.shot("lista")
        s.keys(b"\x1b[B\r", 0.6)                          # traer la primera oculta
        s.click(44, 600 - 17)
        s.keys(b"\x1b[A\x1b[A\r", 1.5)
    t = S.run(script)
    assert not S.errors, S.errors
    for n in S.shots:
        save(S, n)
    px = lambda frame, x, y: frame[(y * 800 + x) * 4 + 2] << 16 | frame[(y * 800 + x) * 4 + 1] << 8 | frame[(y * 800 + x) * 4]  # noqa
    # el menú con las ventanas ocultas se abre encima de la barra
    assert px(S.shots["lista"], 104 + 8 * 64 + 60, 600 - 34 - 20) != px(S.shots["muchas"], 104 + 8 * 64 + 60, 600 - 34 - 20)
    assert "has salido de PyOS LOOK" in t


def test_fuzz_corto_sin_excepciones(image):
    """Versión corta de tests/look_fuzz.py: abre cada aplicación y le manda acciones al azar.
    Ninguna aplicación puede lanzar una excepción (irían a /var/log/look.log)."""
    from tests.look_fuzz import fuzz
    S, t, log = fuzz(seed=7, per_app=12, image=image, verbose=False)
    assert not S.errors, S.errors
    assert "has salido de PyOS LOOK" in t
    assert "No such file" in log, log
