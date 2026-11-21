"""Fuzzer de PyOS LOOK: abre cada aplicación del menú y le manda clics, dobles clics, clics
derechos, arrastres, rueda y teclas aleatorias. Toda excepción de una app queda en
/var/log/look.log (LOOK aísla los fallos), así que lo que aparezca ahí es un bug.

    python tests/look_fuzz.py [semilla] [acciones_por_app] [ancho]x[alto]
"""
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pyos.tools import mkimage  # noqa: E402
from tests.lookdriver import LookSession  # noqa: E402

KEYS = [b"a", b"z", b"1", b"5", b"+", b"-", b" ", b".", b"/", b"\r", b"\x7f", b"\t", b"\x1b",
        b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D", b"\x1b[H", b"\x1b[F", b"\x1b[5~", b"\x1b[6~",
        b"\x1b[3~", b"\x1b[15~", b"\x1b[17~", b"\x1bOR", b"\x1bOQ",
        b"\x01", b"\x03", b"\x06", b"\x0c", b"\x13", b"\x16", b"\x18", b"\x1a", b"\x0f",
        "ñ".encode(), "á".encode(), b"\x1b\t"]
N_APPS = 14          # entradas del menú antes de los plugins/Apps (Terminal ... Acerca de)


def fuzz(seed=1, per_app=80, size=(1024, 768), apps=None, image=None, verbose=True):
    W, H = size
    rng = random.Random(seed)
    if image is None:
        d = tempfile.mkdtemp()
        image = os.path.join(d, "fuzz.img")
        mkimage.build(image, size_mb=16)
    S = LookSession(image, size=size, timeout=600)
    ty = H - 17

    def act(s):
        r = rng.random()
        x = rng.randrange(0, W)
        y = rng.randrange(0, H - 36)             # la barra de tareas solo con clic derecho
        if r < 0.30:
            s.click(x, y)
        elif r < 0.38:
            s.click(x, y, double=True)
        elif r < 0.45:
            s.click(x, y, button=2)
            s.keys(b"\x1b", 0.05)                # cierra el menú contextual... a veces
        elif r < 0.52:
            s.drag(x, y, rng.randrange(0, W), rng.randrange(0, H - 36))
        elif r < 0.58:
            s.goto(x, y)
            s.machine.mouse.scroll(rng.choice((-3, -1, 1, 2)))
            time.sleep(0.05)
        elif r < 0.62:
            s.click(rng.randrange(110, W - 130), ty, button=2)   # menú de una tarea
        else:
            s.keys(rng.choice(KEYS), 0.02)

    def script(s):
        order = apps if apps is not None else list(range(N_APPS))
        for idx in order:
            s.keys(b"\x1b\x1b", 0.1)
            s.click(44, ty)                      # menú PyOS
            s.keys(b"\x1b[B" * (idx + 1) + b"\r", 0.5)
            for _ in range(per_app):
                act(s)
            if verbose:
                print("app %d hecha" % idx, flush=True)
        for _ in range(4):
            s.keys(b"\x1b", 0.1)
        # salir de LOOK por el menú (2 por debajo: "Salir a PyOS Term"). Si hay documentos sin
        # guardar, LOOK pregunta con "Cancelar" preseleccionado: flecha izquierda + Intro confirma.
        for _ in range(3):
            s.keys(b"\x1b\x1b", 0.2)
            s.click(44, ty)
            s.keys(b"\x1b[A\x1b[A\r", 2.0)
            if s.machine.kernel.gfx.owner is None:
                break
            s.keys(b"\x1b[D\r", 2.0)
            if s.machine.kernel.gfx.owner is None:
                break

    S.after = ["cat /var/log/look.log", "halt"]
    t = S.run(script)
    log = t.split("cat /var/log/look.log", 1)[1].split("root@pyos", 1)[0] if "cat /var/log/look.log" in t else t[-3000:]
    return S, t, log


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    size = tuple(int(v) for v in sys.argv[3].split("x")) if len(sys.argv) > 3 else (1024, 768)
    S, t, log = fuzz(seed, n, size)
    print("errores del guion:", S.errors)
    print("salió de LOOK:", "has salido de PyOS LOOK" in t)
    print("look.log:\n" + log)
