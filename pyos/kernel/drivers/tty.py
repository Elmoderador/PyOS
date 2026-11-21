"""Driver TTY: disciplina de línea sobre teclado PS/2 y/o UART.

Modo canónico: eco, retroceso consciente de UTF-8, Ctrl-U, Ctrl-C (SIGINT al
grupo en primer plano), Ctrl-D (EOF), CR->LF en entrada y LF->CRLF en salida.

Modo crudo (juegos, editores a pantalla completa): los bytes llegan tal cual y
sin eco; se conservan Ctrl-C (SIGINT) y Ctrl-] (botón de encendido). Lo activa un
proceso con ttyctl("raw", True) y el kernel lo desactiva si ese proceso muere.
"""
from collections import deque

from ..errors import KError, EINTR
from ..fs.vfs import FileOps
from ..proc.process import SIGINT, Block, WaitQueue
from .devices import CharDevice

MAX_LINE = 4096


class _TTYOps(FileOps):
    seekable = False

    def __init__(self, tty):
        self.tty = tty

    def read(self, of, n):
        return self.tty.read(n)

    def write(self, of, data):
        return self.tty.write(data)


class TTY(CharDevice):
    name, major, minor = "tty", 4, 0
    description = "consola con disciplina de línea"

    def __init__(self, kernel, screen, uart):
        self.k = kernel
        self.screen = screen
        self.uart = uart if (uart is not None and uart.present) else None
        self.irq = 4 if self.uart else None
        self.line = bytearray()
        self.cooked = deque()
        self.wq = WaitQueue(kernel, "tty")
        self.fg = set()
        self.rx_bytes = 0
        self.esc = 0                   # 0 nada, 1 tras ESC, 2 dentro de ESC [ ... (modo canónico)
        self.raw_isig = True
        self.raw_owner = None          # pid del proceso que puso la consola en modo crudo
        self.on_raw_input = None       # aviso al driver gráfico (LOOK espera teclas)
        self.rawbuf = bytearray()

    def open(self, flags):
        return _TTYOps(self)

    def _echo(self, data):
        self.screen.write(data)

    def uart_interrupt(self):
        got = False
        while True:
            b = self.uart.read_byte()
            if b is None:
                break
            got = self._input(b) or got
        if got:
            self.wq.wake_all()

    def feed(self, data):
        """Entrada procedente del driver de teclado."""
        got = False
        for b in data:
            got = self._input(b) or got
        if got:
            self.wq.wake_all()

    def _input(self, b):
        self.rx_bytes += 1
        if self.raw_owner is not None:
            if b == 0x03 and self.raw_isig:
                for pid in list(self.fg):
                    p = self.k.procs.get(pid)
                    if p:
                        self.k.send_signal(p, SIGINT)
                return True
            if b == 0x1D:
                self.k.power_button()
                return False
            if len(self.rawbuf) < MAX_LINE:
                self.rawbuf.append(b)
            if self.on_raw_input is not None:
                self.on_raw_input()
            return True
        if self.esc:                   # secuencias de escape (flechas...): se descartan enteras
            if self.esc == 1:
                self.esc = 2 if b == 0x5B else (3 if b == 0x4F else 0)
                return False
            if self.esc == 3:                  # ESC O x (teclas de función)
                self.esc = 0
                return False
            if 0x40 <= b <= 0x7E:
                self.esc = 0
            return False
        if b == 0x0D:
            b = 0x0A
        if b == 0x03:
            self._echo(b"^C\r\n")
            self.line = bytearray()
            for pid in list(self.fg):
                p = self.k.procs.get(pid)
                if p:
                    self.k.send_signal(p, SIGINT)
            return True
        if b == 0x04:
            self.cooked.append(bytes(self.line) if self.line else b"")
            self.line = bytearray()
            return True
        if b == 0x1D:
            self.k.power_button()
            return False
        if b in (0x7F, 0x08):
            if self.line:
                while self.line and (self.line[-1] & 0xC0) == 0x80:
                    self.line.pop()
                if self.line:
                    self.line.pop()
                self._echo(b"\b \b")
            return False
        if b == 0x15:
            n = len(self.line.decode("utf-8", "replace"))
            self._echo(b"\b \b" * n)
            self.line = bytearray()
            return False
        if b == 0x1B:      # secuencias de escape (flechas): se ignoran en modo canónico
            self.esc = 1
            return False
        if b == 0x0A:
            self.line.append(b)
            self._echo(b"\r\n")
            self.cooked.append(bytes(self.line))
            self.line = bytearray()
            return True
        if (b >= 0x20 or b == 0x09) and len(self.line) < MAX_LINE:
            self.line.append(b)
            self._echo(bytes([b]))
        return False

    def read(self, n):
        proc = self.k.current
        if self.raw_owner is not None:
            if not self.rawbuf:
                if proc.pending_signals:
                    raise KError(EINTR)
                raise Block(self.wq)
            return self.read_nowait(n)
        if not self.cooked:
            if proc.pending_signals:
                raise KError(EINTR)
            raise Block(self.wq)
        chunk = self.cooked.popleft()
        if chunk == b"":
            return b""
        if len(chunk) > n:
            self.cooked.appendleft(chunk[n:])
            chunk = chunk[:n]
        return chunk

    # ------------------------------------------------------------ modo crudo
    def set_raw(self, pid, on, isig=True):
        """isig=False: Ctrl-C llega como byte 0x03 (como cfmakeraw); lo usa LOOK, que
        reparte el Ctrl-C a la terminal que tenga el foco."""
        if on:
            self.raw_owner = pid
            self.raw_isig = isig
            self.esc = 0
            self.line = bytearray()
            self.rawbuf = bytearray()
        elif self.raw_owner == pid:
            self.raw_owner = None
            self.rawbuf = bytearray()
            self._back_to_gfx()

    def read_nowait(self, n):
        chunk = bytes(self.rawbuf[:n])
        del self.rawbuf[:len(chunk)]
        return chunk

    def release(self, pid):
        """El proceso que tenía la consola en modo crudo ha muerto: se restaura."""
        if self.raw_owner == pid:
            self.raw_owner = None
            self.rawbuf = bytearray()
            if not self._back_to_gfx():
                self.write(b"\x1b[0m\x1b[2J\x1b[H")

    def _back_to_gfx(self):
        """Un programa a pantalla completa lanzado desde un terminal de LOOK terminó:
        el teclado vuelve a LOOK (dueño de la pantalla gráfica)."""
        gfx = getattr(self.k, "gfx", None)
        if gfx is not None and gfx.owner is not None and gfx.owner in self.k.procs:
            self.raw_owner = gfx.owner
            return True
        return False

    def size(self):
        f = getattr(self.screen, "size", None)
        try:
            cols, rows = f() if f is not None else (80, 25)
        except Exception:
            cols, rows = 80, 25
        return int(cols), int(rows)

    def write(self, data):
        data = bytes(data)
        if getattr(self.screen, "ansi", False):
            # La pantalla interpreta las secuencias ANSI (posición, borrado...).
            self.screen.write(data.replace(b"\n", b"\r\n"))
            return len(data)
        if b"\x1b[2J" in data:
            before, _, after = data.partition(b"\x1b[2J")
            if before:
                self.write(before)
            clear = getattr(self.screen, "clear", None)
            if clear is not None:
                clear()
            if after:
                self.write(after)
            return len(data)
        self.screen.write(data.replace(b"\n", b"\r\n"))
        return len(data)
