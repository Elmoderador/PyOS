"""Máquina emulada en el host (desarrollo y tests). Sin hilos: todo por sondeo."""
import os
import sys
import time

from . import MachineCheck

SECTOR = 512


class RAM(object):
    def __init__(self, size):
        if size <= 0 or size % 4096:
            raise ValueError("RAM debe ser múltiplo de 4096")
        self.size = size
        self._m = bytearray(size)

    def _check(self, a, n):
        if a < 0 or n < 0 or a + n > self.size:
            raise MachineCheck("acceso físico fuera de rango: %#x+%d" % (a, n))

    def read(self, a, n):
        self._check(a, n)
        return bytes(self._m[a:a + n])

    def write(self, a, data):
        n = len(data)
        self._check(a, n)
        self._m[a:a + n] = data

    def fill(self, a, n, v=0):
        self._check(a, n)
        self._m[a:a + n] = bytes([v]) * n

    def read_u32(self, a):
        self._check(a, 4)
        return int.from_bytes(self._m[a:a + 4], "little")

    def write_u32(self, a, v):
        self._check(a, 4)
        self._m[a:a + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")

    def find_byte(self, v, s, e):
        self._check(s, e - s)
        return self._m.find(bytes([v]), s, e)


class FileDisk(object):
    def __init__(self, path):
        self.path = path
        self._f = open(path, "r+b")
        self._f.seek(0, 2)
        size = self._f.tell()
        if size % SECTOR:
            raise MachineCheck("imagen de disco no múltiplo de 512")
        self.sectors = size // SECTOR
        self.reads = self.writes = 0

    def read(self, lba, n):
        if lba < 0 or n < 0 or lba + n > self.sectors:
            raise MachineCheck("lectura fuera de rango lba=%d n=%d" % (lba, n))
        self._f.seek(lba * SECTOR)
        self.reads += n
        return self._f.read(n * SECTOR)

    def write(self, lba, data):
        if len(data) % SECTOR:
            raise MachineCheck("escritura no alineada")
        n = len(data) // SECTOR
        if lba < 0 or lba + n > self.sectors:
            raise MachineCheck("escritura fuera de rango lba=%d n=%d" % (lba, n))
        self._f.seek(lba * SECTOR)
        self._f.write(data)
        self.writes += n

    def flush(self):
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except (OSError, AttributeError):
            pass

    def close(self):
        if not self._f.closed:
            self._f.close()


# ------------------------------------------------------------------ consola
class TerminalConsole(object):
    """Terminal del host en modo raw, leído por sondeo (sin hilos)."""
    POWER_KEY = 0x1D  # Ctrl-]

    def __init__(self):
        self._restore = None
        self._pending = bytearray()
        self.power_pressed = False
        self.present = True
        self.eof = False
        fd = sys.stdin.fileno()
        if os.name != "nt" and os.isatty(fd):
            import termios
            import tty
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _poll(self):
        if os.name == "nt":  # pragma: no cover
            import msvcrt
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    continue
                self._pending += ch.encode("utf-8")
        else:
            import select
            fd = sys.stdin.fileno()
            while not self.eof and select.select([fd], [], [], 0)[0]:
                data = os.read(fd, 256)
                if not data:
                    self.eof = True
                    self._pending.append(4)
                    break
                self._pending += data
        if self.POWER_KEY in self._pending:
            self._pending = self._pending.replace(bytes([self.POWER_KEY]), b"")
            self.power_pressed = True

    def has_data(self):
        self._poll()
        return bool(self._pending)

    def read_byte(self):
        if not self._pending:
            self._poll()
        if self._pending:
            b = self._pending[0]
            del self._pending[0]
            return b
        return None

    ansi = True                      # el terminal del host interpreta ANSI

    def size(self):
        import shutil
        sz = shutil.get_terminal_size((80, 25))
        return sz.columns, sz.lines

    def write(self, data):
        out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
        out.write(data)
        out.flush()

    def clear(self):
        self.write(b"\x1b[2J\x1b[H")

    def close(self):
        if self._restore:
            self._restore()
            self._restore = None


class Raw(object):
    """Paso de guion: bytes tal cual tras `delay` segundos."""

    def __init__(self, data, delay=0.0):
        self.data, self.delay = data, delay


class ScriptConsole(object):
    """Teclea un guion: cada línea se envía cuando aparece el prompt."""

    def __init__(self, steps, prompt=b"# ", echo=False, eof_at_end=True, timeout=60.0,
                 clock=time.time):
        self.steps = list(steps)
        self.prompt = prompt
        self.echo = echo
        self.eof_at_end = eof_at_end
        self.timeout = timeout
        self.clock = clock
        self.buf = bytearray()
        self.seen = 0
        self._pending = bytearray()
        self._raw_at = None
        self.present = True
        self.power_pressed = False
        self.started = clock()
        self.last_progress = clock()

    def size(self):
        return (80, 25)

    @property
    def transcript(self):
        return self.buf.decode("utf-8", "replace").replace("\r\n", "\n")

    def _poll(self):
        now = self.clock()
        if not self.steps:
            if self.eof_at_end is not None and self._prompt_ready():
                self._pending.append(4)
                self.eof_at_end = None
            elif now - self.last_progress > self.timeout:
                self.power_pressed = True
            return
        step = self.steps[0]
        if isinstance(step, Raw):
            if self._raw_at is None:
                self._raw_at = now + step.delay
            if now >= self._raw_at:
                self._pending += step.data
                self.steps.pop(0)
                self._raw_at = None
                self.last_progress = now
        elif self._prompt_ready():
            self._pending += step.encode("utf-8") + b"\r"
            self.steps.pop(0)
            self.last_progress = now
        elif now - self.last_progress > self.timeout:
            self.power_pressed = True

    def _prompt_ready(self):
        idx = self.buf.find(self.prompt, self.seen)
        if idx >= 0:
            self.seen = idx + len(self.prompt)
            return True
        return False

    def has_data(self):
        self._poll()
        return bool(self._pending)

    def read_byte(self):
        if not self._pending:
            self._poll()
        if self._pending:
            b = self._pending[0]
            del self._pending[0]
            return b
        return None

    def write(self, data):
        self.buf += data
        if self.echo:
            out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
            out.write(data)
            out.flush()

    def close(self):
        pass


class LinuxBridge(object):
    """Procesos Linux reales (subprocess) con tuberías no bloqueantes. Sin hilos."""

    def __init__(self):
        import subprocess
        self._sp = subprocess
        self.procs = {}
        self.next = 1

    @staticmethod
    def supported():
        return sys.platform.startswith("linux")

    def info(self):
        distro = "?"
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        distro = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        u = os.uname()
        return {"kernel": "%s %s" % (u.sysname, u.release), "distro": distro, "arch": u.machine}

    def spawn(self, argv):
        try:
            p = self._sp.Popen(list(argv), stdin=self._sp.PIPE, stdout=self._sp.PIPE,
                               stderr=self._sp.STDOUT, start_new_session=True)
        except OSError as e:
            raise OSError(e.errno or 2, "no se pudo lanzar %s: %s" % (argv[0], e.strerror))
        os.set_blocking(p.stdout.fileno(), False)
        h = self.next
        self.next += 1
        self.procs[h] = {"p": p, "buf": bytearray(), "eof": False, "argv": list(argv)}
        return h

    def poll(self):
        changed = False
        for st in self.procs.values():
            if not st["eof"]:
                try:
                    data = os.read(st["p"].stdout.fileno(), 65536)
                except BlockingIOError:
                    data = None
                except OSError:
                    data = b""
                if data:
                    st["buf"] += data
                    changed = True
                elif data == b"":
                    st["eof"] = True
                    changed = True
            if st["eof"] and st.get("rc") is None and st["p"].poll() is not None:
                st["rc"] = st["p"].returncode
                changed = True
        return changed

    def read(self, h, n):
        st = self.procs[h]
        data = bytes(st["buf"][:n])
        del st["buf"][:len(data)]
        return data, (st["eof"] and not st["buf"] and not data)

    def write(self, h, data):
        st = self.procs[h]
        try:
            st["p"].stdin.write(data)
            st["p"].stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            return -32
        return len(data)

    def close_stdin(self, h):
        try:
            self.procs[h]["p"].stdin.close()
        except OSError:
            pass

    def status(self, h):
        st = self.procs.get(h)
        if st is None:
            return None
        rc = st.get("rc")
        if rc is None:
            return None
        return rc if rc >= 0 else 128 - rc

    def kill(self, h):
        st = self.procs.get(h)
        if st and st["p"].poll() is None:
            st["p"].kill()

    def forget(self, h):
        st = self.procs.pop(h, None)
        if st:
            for f in (st["p"].stdin, st["p"].stdout):
                try:
                    f.close()
                except OSError:
                    pass

    def host_pid(self, h):
        st = self.procs.get(h)
        return st["p"].pid if st else "-"

    def argv(self, h):
        st = self.procs.get(h)
        return st["argv"] if st else []


class _NoKbd(object):
    present = False

    def read_scancode(self):
        return None


class MemFramebuffer(object):
    """Framebuffer XRGB8888 en memoria (modo alojado y tests). Exportable a PNG."""
    desc = "framebuffer en memoria"

    def __init__(self, width=1024, height=768):
        self.width = width
        self.height = height
        self.pitch = width * 4
        self.buf = bytearray(self.pitch * height)
        self.calls = 0
        self.fast = True

        self.last_frame = None

    def begin(self):
        pass

    def end(self):
        pass

    def snapshot(self):
        self.last_frame = bytes(self.buf)

    def span(self, x, y, n, rgb):
        o = y * self.pitch + 4 * x
        self.buf[o:o + 4 * n] = rgb.to_bytes(4, "little") * n
        self.calls += 1

    def spans(self, items, rgb):
        for x, y, n in items:
            self.span(x, y, n, rgb)

    def pixels(self, x, y, rgbs):
        o = y * self.pitch + 4 * x
        self.buf[o:o + 4 * len(rgbs)] = b"".join(c.to_bytes(4, "little") for c in rgbs)
        self.calls += len(rgbs)

    def read(self, x, y, n):
        o = y * self.pitch + 4 * x
        b = self.buf[o:o + 4 * n]
        return [b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) for i in range(0, 4 * n, 4)]

    def pixel(self, x, y):
        return self.read(x, y, 1)[0]

    def info(self):
        return {"adapter": self.desc, "width": self.width, "height": self.height,
                "copy": "memoria"}

    def png(self, frame=None):
        import struct
        import zlib
        src = self.buf if frame is None else frame
        raw = bytearray()
        for y in range(self.height):
            raw.append(0)
            row = src[y * self.pitch:(y + 1) * self.pitch]
            for i in range(0, len(row), 4):
                raw += bytes((row[i + 2], row[i + 1], row[i]))

        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


class FakeMouse(object):
    """Ratón PS/2 simulado: genera paquetes de 3 bytes reales para el driver."""

    def __init__(self):
        import collections
        self.q = collections.deque()          # los tests inyectan desde otro hilo
        self.mouse_on = False
        self.buttons = 0
        self.wheel = True                     # se comporta como un IntelliMouse
        self.packet_size = 3

    def mouse_enable(self, clock):
        self.mouse_on = True
        self.packet_size = 4 if self.wheel else 3
        return True

    def _pad(self):
        return (0,) if self.packet_size == 4 else ()

    def mouse_disable(self, clock):
        self.mouse_on = False

    def mouse_bytes(self):
        out = []
        q = self.q
        while q:
            out.append(q.popleft())
        return out

    def move(self, dx, dy, buttons=None):
        """dy positivo = hacia abajo en pantalla (el paquete PS/2 lo lleva invertido)."""
        if buttons is not None:
            self.buttons = buttons
        while dx or dy:
            sx = max(-255, min(255, dx))
            sy = max(-255, min(255, dy))
            py = -sy
            b0 = 0x08 | (self.buttons & 7) | (0x10 if sx < 0 else 0) | (0x20 if py < 0 else 0)
            self.q.extend((b0, sx & 0xFF, py & 0xFF) + self._pad())
            dx -= sx
            dy -= sy

    def set_buttons(self, b):
        self.buttons = b
        self.q.extend((0x08 | (b & 7), 0, 0) + self._pad())

    def scroll(self, dz):
        """dz > 0: rueda hacia el usuario (bajar)."""
        self.q.extend((0x08 | (self.buttons & 7), 0, 0, dz & 0xFF))


class Machine(object):
    kind = "emulated"

    def __init__(self, ram_size, disk_path, console, linux=False):
        self.ram = RAM(ram_size)
        self.disk = FileDisk(disk_path)
        self.console = console      # pantalla
        self.uart = console         # y entrada (línea serie)
        self.kbd = _NoKbd()
        self.mouse = FakeMouse()
        self.fb = MemFramebuffer(*getattr(console, "fb_size", (1024, 768)))
        self.t0 = time.perf_counter()
        self.halted_with = None
        # Opt-in explícito: da a los procesos PyOS acceso a ejecutables del host.
        self.linux = LinuxBridge() if (linux and LinuxBridge.supported()) else None

    def framebuffer(self):
        return self.fb

    def text_console_restore(self):
        self.console.suspended = False

    def clock(self):
        return time.perf_counter() - self.t0

    def wall(self):
        return time.time()

    def power_button_pressed(self):
        if self.console.power_pressed:
            self.console.power_pressed = False
            return True
        return False

    def idle(self):
        time.sleep(0.001)

    def power_off(self):
        self.halted_with = "poweroff"

    def reset(self):
        self.halted_with = "reboot"

    def random_bytes(self, n):
        return os.urandom(n)

    def boot_entries(self):
        return []           # una máquina emulada no tiene otras particiones arrancables

    def chainload(self, loader):
        return -1

    def info(self):
        import platform
        return {"platform": "máquina emulada (host %s, CPython %s)" % (platform.system(), platform.python_version()),
                "cpu": platform.machine() or "?", "timer": "perf_counter del host",
                "pci": [], "firmware": "PyOS BIOS emulada"}

    def shutdown(self):
        if self.linux is not None:
            for h in list(self.linux.procs):
                self.linux.kill(h)
                self.linux.forget(h)
        self.disk.close()
        self.console.close()
