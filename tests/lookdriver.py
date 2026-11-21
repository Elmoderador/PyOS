"""Conduce PyOS LOOK en la máquina emulada: ratón y teclado simulados, capturas PNG."""
import threading
import time

from pyos.__main__ import run_machine
from pyos.hal import emulated
from pyos.hal.emulated import Raw, ScriptConsole


class LookSession(object):
    def __init__(self, image, mem=16 << 20, timeout=60, size=(1024, 768)):
        self.image = image
        self.size = size
        self.mem = mem
        self.timeout = timeout
        self.machine = None
        self.con = None
        self.shots = {}
        self.errors = []
        self.after = ["halt"]

    # --- acciones (se llaman desde el guion, en otro hilo)
    def wait_gfx(self, t=30):
        end = time.time() + t
        while time.time() < end:
            m = self.machine
            if m is not None and m.fb.calls > 1000:
                time.sleep(0.5)
                return True
            time.sleep(0.05)
        raise AssertionError("LOOK no llegó a dibujar")

    def pos(self):
        return self.kernel_gfx().mx, self.kernel_gfx().my

    def kernel_gfx(self):
        return self.machine.kernel.gfx

    def goto(self, x, y):
        """Mueve el ratón a (x, y) (sin aceleración: pasos de 6)."""
        for _ in range(400):
            cx, cy = self.pos()
            dx, dy = x - cx, y - cy
            if not dx and not dy:
                return
            self.machine.mouse.move(max(-6, min(6, dx)), max(-6, min(6, dy)))
            time.sleep(0.004)
        raise AssertionError("el ratón no llegó a %r" % ((x, y),))

    def click(self, x, y, double=False, button=1):
        self.goto(x, y)
        time.sleep(0.05)
        for _ in range(2 if double else 1):
            self.machine.mouse.set_buttons(button)
            time.sleep(0.03)
            self.machine.mouse.set_buttons(0)
            time.sleep(0.05)
        time.sleep(0.3)

    def drag(self, x0, y0, x1, y1):
        self.goto(x0, y0)
        self.machine.mouse.set_buttons(1)
        time.sleep(0.05)
        steps = 10
        for i in range(1, steps + 1):
            self.machine.mouse.move((x1 - x0) // steps if i < steps else (x1 - x0) - (x1 - x0) // steps * (steps - 1),
                                    (y1 - y0) // steps if i < steps else (y1 - y0) - (y1 - y0) // steps * (steps - 1))
            time.sleep(0.03)
        self.machine.mouse.set_buttons(0)
        time.sleep(0.3)

    def keys(self, data, wait=0.4):
        self.con.inject(data)
        time.sleep(wait)

    def shot(self, name, wait=0.6):
        time.sleep(wait)
        self.shots[name] = bytes(self.machine.fb.buf)

    def pixel(self, x, y):
        return self.machine.fb.pixel(x, y)

    # --- ejecución
    def run(self, script, mode="look"):
        sess = self
        orig = emulated.Machine.__init__

        def init(m, *a, **k):
            orig(m, *a, **k)
            sess.machine = m
        con = InjectConsole(self.after, timeout=self.timeout)
        con.fb_size = self.size
        self.con = con
        emulated.Machine.__init__ = init

        def runner():
            try:
                self.wait_gfx()
                script(self)
            except BaseException as e:      # noqa
                import traceback
                self.errors.append(traceback.format_exc())
            finally:
                con.finish()
        t = threading.Thread(target=runner)
        t.daemon = True
        try:
            t.start()
            rc = run_machine(self.image, self.mem, lambda: con, max_reboots=1, mode=mode)
        finally:
            emulated.Machine.__init__ = orig
        t.join(5)
        self.rc = rc
        return con.transcript

    def png(self, name):
        return self.machine.fb.png(self.shots[name])


class InjectConsole(ScriptConsole):
    """Consola de guion: el hilo de prueba inyecta bytes cuando quiere; al acabar el
    guion se ejecutan los pasos normales (por ejemplo 'halt' en el prompt de Term)."""

    def __init__(self, steps, **kw):
        ScriptConsole.__init__(self, steps, **kw)
        import collections
        self.extra = collections.deque()
        self.done = False

    def inject(self, data):
        for b in data:
            self.extra.append(b)

    def finish(self):
        self.done = True

    def has_data(self):
        if self.extra:
            return True
        if not self.done:
            self.last_progress = self.clock()
            return False
        return ScriptConsole.has_data(self)

    def read_byte(self):
        if self.extra:
            return self.extra.popleft()
        if not self.done:
            self.last_progress = self.clock()
            return None
        return ScriptConsole.read_byte(self)
