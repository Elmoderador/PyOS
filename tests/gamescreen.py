"""Consola de pruebas con pantalla virtual ANSI (para juegos a pantalla completa)."""
from pyos.hal.ansi import GridScreen
from pyos.hal.emulated import ScriptConsole


class GameConsole(ScriptConsole):
    ansi = True

    def __init__(self, steps, cols=80, rows=25, **kw):
        ScriptConsole.__init__(self, steps, **kw)
        self.screen = GridScreen(cols, rows)
        self.snapshots = []

    def size(self):
        return (self.screen.cols, self.screen.rows)

    def write(self, data):
        ScriptConsole.write(self, data)
        self.screen.write(data)
        if b"\x1b[" in data:
            self.snapshots.append(self.screen.dump())

    def find(self, *needles):
        """Última instantánea que contiene todos los textos."""
        for snap in reversed(self.snapshots):
            if all(n in snap for n in needles):
                return snap
        return None
