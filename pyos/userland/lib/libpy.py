# libpy: biblioteca C-equivalente de PyOS. Corre en ESPACIO DE USUARIO.
# Su única puerta al kernel es syscall(num, *args) (vector 0x80).

SYS_EXIT, SYS_SPAWN, SYS_WAITPID, SYS_GETPID, SYS_GETPPID, SYS_KILL = 0, 1, 2, 3, 4, 5
SYS_SLEEP, SYS_YIELD, SYS_FORK, SYS_EXEC = 6, 7, 8, 9
SYS_OPEN, SYS_CLOSE, SYS_READ, SYS_WRITE, SYS_LSEEK, SYS_PIPE, SYS_DUP2 = 10, 11, 12, 13, 14, 15, 16
SYS_STAT, SYS_READDIR, SYS_MKDIR, SYS_RMDIR, SYS_UNLINK, SYS_RENAME = 17, 18, 19, 20, 21, 22
SYS_CHDIR, SYS_GETCWD, SYS_SYNC, SYS_STATFS = 23, 24, 25, 26
SYS_SBRK, SYS_MMAP, SYS_MUNMAP, SYS_MPROTECT, SYS_PEEK, SYS_POKE = 30, 31, 32, 33, 34, 35
SYS_UPTIME, SYS_TIME, SYS_UNAME, SYS_DMESG, SYS_SETFG, SYS_REBOOT = 40, 41, 42, 43, 44, 45
SYS_SIGNAL, SYS_HWINFO, SYS_PYCOMPILE, SYS_KBDLAYOUT = 46, 47, 48, 49
SYS_LX_AVAILABLE, SYS_LX_SPAWN, SYS_LX_READ, SYS_LX_WRITE, SYS_LX_WAIT, SYS_LX_KILL, SYS_LX_CLOSE = 50, 51, 52, 53, 54, 55, 56
SYS_TTYCTL = 57
SYS_GFX_OPEN, SYS_GFX_DRAW, SYS_GFX_POLL, SYS_GFX_CLOSE, SYS_GFX_CURSOR = 58, 59, 60, 61, 62
SYS_FDCTL = 63
SYS_NET_INFO, SYS_NET_CONFIG, SYS_SOCKET, SYS_CONNECT, SYS_BIND, SYS_LISTEN = 64, 65, 66, 67, 68, 69
SYS_ACCEPT, SYS_SENDTO, SYS_RECVFROM, SYS_PING, SYS_RESOLVE = 70, 71, 72, 73, 74
SYS_EXCTB, SYS_KLOG = 75, 76
O_NONBLOCK = 0x800

O_RDONLY, O_WRONLY, O_RDWR = 0, 1, 2
O_CREAT, O_EXCL, O_TRUNC, O_APPEND = 0x40, 0x80, 0x200, 0x400
SEEK_SET, SEEK_CUR, SEEK_END = 0, 1, 2
PROT_NONE, PROT_READ, PROT_WRITE, PROT_EXEC = 0, 1, 2, 4
SIGINT, SIGKILL, SIGSEGV, SIGPIPE, SIGTERM, SIGCHLD = 2, 9, 11, 13, 15, 17
SIGNAL_NAMES = {2: "Interrupt", 9: "Killed", 11: "Segmentation fault", 13: "Broken pipe",
                15: "Terminated"}

ERRORS = {1: "Operation not permitted", 2: "No such file or directory", 3: "No such process",
          4: "Interrupted system call", 5: "I/O error", 8: "Exec format error",
          9: "Bad file descriptor", 10: "No child processes", 11: "Resource temporarily unavailable",
          12: "Out of memory", 13: "Permission denied", 14: "Bad address",
          16: "Device or resource busy", 17: "File exists", 18: "Cross-device link",
          19: "No such device", 20: "Not a directory", 104: "Connection reset by peer", 110: "Connection timed out",
          111: "Connection refused", 113: "No route to host", 98: "Address in use", 107: "Not connected", 21: "Is a directory", 22: "Invalid argument",
          24: "Too many open files", 27: "File too large", 28: "No space left on device",
          29: "Illegal seek", 30: "Read-only file system", 32: "Broken pipe",
          36: "File name too long", 38: "Function not implemented", 39: "Directory not empty"}

STDIN, STDOUT, STDERR = 0, 1, 2


def strerror(errno):
    return ERRORS.get(errno, "Unknown error " + str(errno))


def _check(r):
    if isinstance(r, int) and not isinstance(r, bool) and r < 0:
        raise OSError(-r, strerror(-r))
    return r


# ------------------------------------------------------------------ procesos
def exit(status=0):
    syscall(SYS_EXIT, status)


def spawn(path, argv=None, fds=None, cwd=None):
    return _check(syscall(SYS_SPAWN, path, argv, fds, cwd))


def waitpid(pid=-1, nohang=False):
    return _check(syscall(SYS_WAITPID, pid, nohang))


def getpid():
    return syscall(SYS_GETPID)


def getppid():
    return syscall(SYS_GETPPID)


def kill(pid, sig=SIGTERM):
    return _check(syscall(SYS_KILL, pid, sig))


def sleep_ms(ms):
    return _check(syscall(SYS_SLEEP, int(ms)))


def sched_yield():
    return syscall(SYS_YIELD)


def fork():
    """Duplica el proceso: devuelve 0 en el hijo y el pid del hijo en el padre."""
    return _check(syscall(SYS_FORK))


def exec(path, argv=None):
    """Sustituye la imagen del proceso. Solo vuelve si hay error."""
    return _check(syscall(SYS_EXEC, path, argv))


def signal(sig, handler):
    """handler: función(sig), "ignore" o "default"."""
    return _check(syscall(SYS_SIGNAL, sig, handler))


def status_text(status):
    if status > 128 and status - 128 in SIGNAL_NAMES:
        return SIGNAL_NAMES[status - 128]
    return "exit " + str(status)


# ------------------------------------------------------------------ ficheros
def open(path, flags=O_RDONLY):
    return _check(syscall(SYS_OPEN, path, flags))


def close(fd):
    _buffers.pop(fd, None)
    return _check(syscall(SYS_CLOSE, fd))


def read(fd, n=4096):
    return _check(syscall(SYS_READ, fd, n))


def write(fd, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    total = 0
    while total < len(data):
        total += _check(syscall(SYS_WRITE, fd, data[total:]))
    return total


def lseek(fd, off, whence=SEEK_SET):
    return _check(syscall(SYS_LSEEK, fd, off, whence))


def pipe():
    return _check(syscall(SYS_PIPE))


def dup2(old, new):
    return _check(syscall(SYS_DUP2, old, new))


def stat(path):
    return _check(syscall(SYS_STAT, path))


def exists(path):
    try:
        stat(path)
        return True
    except OSError:
        return False


def listdir(path="."):
    return _check(syscall(SYS_READDIR, path))


def mkdir(path):
    return _check(syscall(SYS_MKDIR, path))


def rmdir(path):
    return _check(syscall(SYS_RMDIR, path))


def unlink(path):
    return _check(syscall(SYS_UNLINK, path))


def rename(a, b):
    return _check(syscall(SYS_RENAME, a, b))


def chdir(path):
    return _check(syscall(SYS_CHDIR, path))


def getcwd():
    return syscall(SYS_GETCWD)


def sync():
    return _check(syscall(SYS_SYNC))


def statfs():
    return _check(syscall(SYS_STATFS))


def read_all(fd):
    chunks = []
    while True:
        c = read(fd, 65536)
        if not c:
            return b"".join(chunks)
        chunks.append(c)


def read_file(path):
    fd = open(path)
    try:
        return read_all(fd)
    finally:
        close(fd)


def write_file(path, data, append=False):
    fd = open(path, O_WRONLY | O_CREAT | (O_APPEND if append else O_TRUNC))
    try:
        return write(fd, data)
    finally:
        close(fd)


_buffers = {}


def readline(fd=STDIN):
    """Lee una línea (incluye '\\n'). Devuelve '' en EOF."""
    buf = _buffers.get(fd, b"")
    while b"\n" not in buf:
        chunk = read(fd, 4096)
        if not chunk:
            _buffers[fd] = b""
            return buf.decode("utf-8", "replace")
        buf += chunk
    i = buf.index(b"\n") + 1
    _buffers[fd] = buf[i:]
    return buf[:i].decode("utf-8", "replace")


def lines(fd=STDIN):
    while True:
        line = readline(fd)
        if not line:
            return
        yield line


# ------------------------------------------------------------------ E/S formateada
def print(*args, sep=" ", end="\n", file=STDOUT):
    write(file, sep.join(str(a) for a in args) + end)


def eprint(*args):
    print(*args, file=STDERR)


def input(prompt=""):
    if prompt:
        write(STDOUT, prompt)
    line = readline(STDIN)
    if not line:
        raise EOFError("EOF")
    return line.rstrip("\n")


# ------------------------------------------------------------------ memoria
def sbrk(incr):
    return _check(syscall(SYS_SBRK, incr))


def mmap(length, prot=PROT_READ | PROT_WRITE):
    return _check(syscall(SYS_MMAP, length, prot))


def munmap(addr, length):
    return _check(syscall(SYS_MUNMAP, addr, length))


def mprotect(addr, length, prot):
    return _check(syscall(SYS_MPROTECT, addr, length, prot))


def peek(addr, n):
    return _check(syscall(SYS_PEEK, addr, n))


def poke(addr, data):
    return _check(syscall(SYS_POKE, addr, data))


# ------------------------------------------------------------------ sistema
def uptime_ms():
    return syscall(SYS_UPTIME)


def time():
    return syscall(SYS_TIME)


def uname():
    return syscall(SYS_UNAME)


def dmesg():
    return syscall(SYS_DMESG)


def setfg(pids):
    return _check(syscall(SYS_SETFG, list(pids)))


def reboot(cmd="poweroff"):
    return _check(syscall(SYS_REBOOT, cmd))


def pycompile(source, filename="<stdin>"):
    """Compila código Python para la PVM. Devuelve (función, es_expresión)."""
    r = syscall(SYS_PYCOMPILE, source, filename)
    if isinstance(r, dict):
        raise SyntaxError(r["error"])
    return _check(r)


def kbdlayout(layout=None):
    return _check(syscall(SYS_KBDLAYOUT, layout))


# ------------------------------------------------------------------ subsistema Linux
def lx_available():
    return syscall(SYS_LX_AVAILABLE)


def lx_spawn(argv):
    return _check(syscall(SYS_LX_SPAWN, list(argv)))


def lx_read(h, n=4096):
    return _check(syscall(SYS_LX_READ, h, n))


def lx_write(h, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _check(syscall(SYS_LX_WRITE, h, data))


def lx_wait(h, nohang=False):
    return _check(syscall(SYS_LX_WAIT, h, nohang))


def lx_kill(h):
    return _check(syscall(SYS_LX_KILL, h))


def lx_close(h):
    return _check(syscall(SYS_LX_CLOSE, h))


# ------------------------------------------------------------------ consola
def ttyctl(op, arg=None):
    return _check(syscall(SYS_TTYCTL, op, arg))


def gfx_open():
    return _check(syscall(SYS_GFX_OPEN))


def gfx_draw(cmds):
    return _check(syscall(SYS_GFX_DRAW, cmds))


def gfx_poll(timeout_ms=0):
    return _check(syscall(SYS_GFX_POLL, timeout_ms))


def gfx_close():
    return _check(syscall(SYS_GFX_CLOSE))


def gfx_cursor(visible=None, x=None, y=None):
    return _check(syscall(SYS_GFX_CURSOR, visible, x, y))


def set_nonblock(fd, on=True):
    return _check(syscall(SYS_FDCTL, fd, "nonblock", on))


# ------------------------------------------------------------------ red
def net_info():
    return syscall(SYS_NET_INFO)


def net_config(spec):
    return _check(syscall(SYS_NET_CONFIG, spec))


def is_ipv4(s):
    p = s.split(".")
    return len(p) == 4 and all(x.isdigit() and int(x) < 256 for x in p)


def resolve(name):
    """Nombre -> lista de IPv4 (cadenas). Acepta ya una IP."""
    if is_ipv4(name):
        return [name]
    return _check(syscall(SYS_RESOLVE, name))


def socket(kind="tcp"):
    return _check(syscall(SYS_SOCKET, kind))


def connect(fd, host, port):
    ips = resolve(host)
    if not ips:
        raise OSError(2, "no se pudo resolver %s" % host)
    return _check(syscall(SYS_CONNECT, fd, ips[0], port))


def bind(fd, port):
    return _check(syscall(SYS_BIND, fd, port))


def listen(fd, backlog=5):
    return _check(syscall(SYS_LISTEN, fd, backlog))


def accept(fd):
    return _check(syscall(SYS_ACCEPT, fd))


def sendto(fd, data, host, port):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _check(syscall(SYS_SENDTO, fd, data, resolve(host)[0], port))


def recvfrom(fd, n=65536):
    return _check(syscall(SYS_RECVFROM, fd, n))


def send_all(fd, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    off = 0
    while off < len(data):
        off += write(fd, data[off:])
    return off


def ping(ip, ident, seq, timeout_ms=2000):
    return _check(syscall(SYS_PING, ip, ident, seq, timeout_ms))


def include(path):
    """Ejecuta un módulo de /lib en los globales del programa (el 'import' de PyOS)."""
    fn, is_expr = pycompile(read_file(path).decode("utf-8"), path)
    fn()


def klog(msg):
    """Escribe una línea en el log del kernel (dmesg)."""
    return _check(syscall(SYS_KLOG, str(msg)))


def exc_traceback(e):
    """[(fichero, línea, función)] de dónde saltó la excepción e (de dentro hacia fuera)."""
    try:
        return syscall(SYS_EXCTB, e)
    except Exception:
        return []


def hwinfo():
    return _check(syscall(SYS_HWINFO))
