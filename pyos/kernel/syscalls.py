"""Tabla de llamadas al sistema (vector 0x80).

Convención: un entero negativo como resultado significa -errno.
Todos los argumentos que vienen de usuario se validan aquí.
"""

from .errors import (KError, EBADF, EFAULT, EINVAL, EMFILE, ENOSYS, ENOTDIR, EPERM,  # noqa: F401
                     ESRCH)
from .fs.pipe import Pipe, PipeReader, PipeWriter
from .fs.vfs import O_RDONLY, O_WRONLY, OpenFile
from .mm.vmm import PROT_EXEC, PROT_READ, PROT_WRITE
from .proc.process import CATCHABLE, SIGINT, SIGKILL, SIGTERM, ProcessExit

MAX_IO = 1 << 20
MAX_FD = 64
_TABLE: dict = {}


def build_table() -> dict:
    return dict(_TABLE)


def syscall(num: int, name: str):
    def deco(fn):
        if num in _TABLE:
            raise RuntimeError(f"syscall duplicada {num}")
        _TABLE[num] = (name, fn)
        return fn
    return deco


# ---------------------------------------------------------------- validación
def _int(v, lo=None, hi=None) -> int:
    if type(v) is not int:
        raise KError(EINVAL)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise KError(EINVAL)
    return v


def _str(v, maxlen=4096) -> str:
    if type(v) is not str or len(v) > maxlen or "\0" in v:
        raise KError(EINVAL)
    return v


def _bytes(v) -> bytes:
    if isinstance(v, str):
        v = v.encode("utf-8")
    if not isinstance(v, (bytes, bytearray)) or len(v) > MAX_IO:
        raise KError(EINVAL)
    return bytes(v)


def _fd(p, fd) -> OpenFile:
    of = p.fds.get(_int(fd, 0, MAX_FD - 1))
    if of is None:
        raise KError(EBADF)
    return of


# ---------------------------------------------------------------- procesos
@syscall(0, "exit")
def sys_exit(k, p, status=0):
    raise ProcessExit(_int(status) & 0xFF)


@syscall(1, "spawn")
def sys_spawn(k, p, path, argv=None, fdmap=None, cwd=None):
    path = _str(path)
    argv = [path] if argv is None else argv
    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > 128:
        raise KError(EINVAL)
    argv = [_str(a) for a in argv]
    cwd = p.cwd if cwd is None else k.vfs.normalize(_str(cwd), p.cwd)
    if fdmap is None:
        fdmap = {i: i for i in (0, 1, 2) if i in p.fds}
    if not isinstance(fdmap, dict) or len(fdmap) > MAX_FD:
        raise KError(EINVAL)
    fds = {}
    for cfd, pfd in fdmap.items():
        _int(cfd, 0, MAX_FD - 1)
        of = _fd(p, pfd)
        fds[cfd] = of
    for of in fds.values():
        of.dup()
    try:
        return k.spawn(p, path, argv, fds, cwd).pid
    except BaseException:
        for of in fds.values():
            of.close()
        raise


@syscall(2, "waitpid")
def sys_waitpid(k, p, pid=-1, nohang=False):
    return k.reap(p, _int(pid, -1), bool(nohang))


@syscall(3, "getpid")
def sys_getpid(k, p):
    return p.pid


@syscall(4, "getppid")
def sys_getppid(k, p):
    return p.ppid


@syscall(5, "kill")
def sys_kill(k, p, pid, sig=SIGTERM):
    pid = _int(pid, 0)
    if _int(sig) not in (SIGINT, SIGKILL, SIGTERM):
        raise KError(EINVAL)
    target = k.procs.get(pid)
    if target is None or pid == 0:
        raise KError(ESRCH)
    if pid == 1:
        raise KError(EPERM, "init ignora señales")
    k.send_signal(target, sig)
    return 0


@syscall(6, "sleep")
def sys_sleep(k, p, ms):
    return k.sleep(p, _int(ms, 0, 3600000))


@syscall(7, "yield")
def sys_yield(k, p):
    k.sched.need_resched = True
    return 0


@syscall(8, "fork")
def sys_fork(k, p):
    return k.fork(p)


@syscall(9, "exec")
def sys_exec(k, p, path, argv=None):
    path = _str(path)
    argv = [path] if argv is None else argv
    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > 128:
        raise KError(EINVAL)
    k.exec(p, path, [_str(a) for a in argv])
    return None     # no vuelve: la imagen del proceso ha sido sustituida


# ---------------------------------------------------------------- ficheros
@syscall(10, "open")
def sys_open(k, p, path, flags=O_RDONLY):
    of = k.vfs.open(_str(path), _int(flags, 0, 0xFFFF), p.cwd)
    fd = p.alloc_fd(of, 0, MAX_FD)
    if fd < 0:
        of.close()
        raise KError(EMFILE)
    return fd


@syscall(11, "close")
def sys_close(k, p, fd):
    of = _fd(p, fd)
    del p.fds[fd]
    of.close()
    return 0


@syscall(12, "read")
def sys_read(k, p, fd, n):
    return _fd(p, fd).read(_int(n, 0, MAX_IO))


@syscall(13, "write")
def sys_write(k, p, fd, data):
    return _fd(p, fd).write(_bytes(data))


@syscall(14, "lseek")
def sys_lseek(k, p, fd, off, whence=0):
    return _fd(p, fd).seek(_int(off), _int(whence, 0, 2))


@syscall(15, "pipe")
def sys_pipe(k, p):
    pipe = Pipe(k)
    r = OpenFile(PipeReader(pipe), O_RDONLY, "pipe:[r]")
    w = OpenFile(PipeWriter(pipe), O_WRONLY, "pipe:[w]")
    rfd = p.alloc_fd(r, 0, MAX_FD)
    wfd = p.alloc_fd(w, 0, MAX_FD) if rfd >= 0 else -1
    if wfd < 0:
        if rfd >= 0:
            del p.fds[rfd]
        r.close()
        w.close()
        raise KError(EMFILE)
    return (rfd, wfd)


@syscall(16, "dup2")
def sys_dup2(k, p, old, new):
    of = _fd(p, old)
    new = _int(new, 0, MAX_FD - 1)
    if new == old:
        return new
    if new in p.fds:
        p.fds.pop(new).close()
    p.fds[new] = of.dup()
    return new


@syscall(17, "stat")
def sys_stat(k, p, path):
    return k.vfs.stat(_str(path), p.cwd)


@syscall(18, "readdir")
def sys_readdir(k, p, path):
    return [tuple(e) for e in k.vfs.readdir(_str(path), p.cwd)]


@syscall(19, "mkdir")
def sys_mkdir(k, p, path):
    k.vfs.mkdir(_str(path), p.cwd)
    return 0


@syscall(20, "rmdir")
def sys_rmdir(k, p, path):
    k.vfs.rmdir(_str(path), p.cwd)
    return 0


@syscall(21, "unlink")
def sys_unlink(k, p, path):
    k.vfs.unlink(_str(path), p.cwd)
    return 0


@syscall(22, "rename")
def sys_rename(k, p, old, new):
    k.vfs.rename(_str(old), _str(new), p.cwd)
    return 0


@syscall(23, "chdir")
def sys_chdir(k, p, path):
    target = k.vfs.normalize(_str(path), p.cwd)
    if k.vfs.stat(target)["type"] != "dir":
        raise KError(ENOTDIR)
    p.cwd = target
    return 0


@syscall(24, "getcwd")
def sys_getcwd(k, p):
    return p.cwd


@syscall(25, "sync")
def sys_sync(k, p):
    k.vfs.sync()
    return 0


@syscall(26, "statfs")
def sys_statfs(k, p):
    return k.rootfs.statfs()


# ---------------------------------------------------------------- memoria
def _prot(v) -> int:
    v = _int(v, 0, 7)
    return v & (PROT_READ | PROT_WRITE | PROT_EXEC)


@syscall(30, "sbrk")
def sys_sbrk(k, p, incr):
    return p.aspace.sbrk(_int(incr, -(1 << 30), 1 << 30))


@syscall(31, "mmap")
def sys_mmap(k, p, length, prot=PROT_READ | PROT_WRITE):
    length = _int(length, 1, 1 << 30)
    addr = p.aspace.find_free(length)
    p.aspace.map(addr, length, _prot(prot), "anon")
    return addr


@syscall(32, "munmap")
def sys_munmap(k, p, addr, length):
    p.aspace.unmap(_int(addr, 0), _int(length, 1))
    return 0


@syscall(33, "mprotect")
def sys_mprotect(k, p, addr, length, prot):
    p.aspace.protect(_int(addr, 0), _int(length, 1), _prot(prot))
    return 0


@syscall(34, "peek")
def sys_peek(k, p, addr, n):
    return p.aspace.read(_int(addr), _int(n, 0, MAX_IO))


@syscall(35, "poke")
def sys_poke(k, p, addr, data):
    p.aspace.write(_int(addr), _bytes(data))
    return 0


# ---------------------------------------------------------------- sistema
@syscall(40, "uptime")
def sys_uptime(k, p):
    return k.sched.ticks * 1000 // k.hz


@syscall(41, "time")
def sys_time(k, p):
    return k.m.wall()


@syscall(42, "uname")
def sys_uname(k, p):
    import sys
    from .main import VERSION
    return ("PyOS", "pyos", VERSION, "CPython " + sys.version.split()[0], k.m.kind)


@syscall(43, "dmesg")
def sys_dmesg(k, p):
    return k.log.dump()


@syscall(44, "setfg")
def sys_setfg(k, p, pids):
    if not isinstance(pids, (list, tuple)) or len(pids) > MAX_FD:
        raise KError(EINVAL)
    k.tty.fg = {_int(x, 1) for x in pids}
    return 0


@syscall(46, "signal")
def sys_signal(k, p, sig, handler):
    sig = _int(sig)
    if sig not in CATCHABLE:
        raise KError(EINVAL, "señal no capturable")
    from .cpu.vm import VMFunction
    if handler is None or handler == "default":
        p.sighandlers.pop(sig, None)
    elif handler == "ignore" or type(handler) is VMFunction:
        p.sighandlers[sig] = handler
    else:
        raise KError(EINVAL)
    return 0


@syscall(47, "hwinfo")
def sys_hwinfo(k, p):
    return dict(k.m.info())


@syscall(48, "pycompile")
def sys_pycompile(k, p, source, filename="<stdin>"):
    """Compila código Python a la PVM y lo devuelve como función ejecutable.

    Si el código es una sola expresión, guarda su valor en `_` (modo REPL).
    Devuelve (función, es_expresión) o {"error": mensaje} si no compila.
    """
    import ast
    from .cpu.compiler import CompileError, compile_source
    from .cpu.vm import VMFunction
    source = _str(source, 1 << 20)
    filename = _str(filename, 256)
    is_expr = False
    if filename.startswith("/"):              # fichero (include, scripts): caché SHA-256 del cargador
        try:
            code = k.loader.load(source.encode("utf-8"), filename)
            return (VMFunction(code, p.globals, (), {}, ()), False)
        except KError as e:
            return {"error": str(e.args[1]) if len(e.args) > 1 else str(e)}
    try:
        tree = ast.parse(source, filename)
        if len(tree.body) == 1 and type(tree.body[0]).__name__ == "Expr":
            is_expr = True
            source = "_ = (" + source.strip() + "\n)\n"
        code = compile_source(source, filename)
    except SyntaxError as e:
        return {"error": "%s, línea %s: %s" % (filename, e.lineno, e.msg)}
    except CompileError as e:
        return {"error": str(e)}
    return (VMFunction(code, p.globals, (), {}, ()), is_expr)


@syscall(49, "kbdlayout")
def sys_kbdlayout(k, p, layout=None):
    if k.kbd is None:
        raise KError(19, "no hay teclado PS/2 (consola serie o emulada)")
    if layout is not None:
        from .drivers.ps2kbd import LAYOUTS
        if _str(layout, 8) not in LAYOUTS:
            raise KError(EINVAL)
        k.kbd.set_layout(layout)
        k.log("teclado: distribución cambiada a '%s'" % layout)
    return k.kbd.layout_name


@syscall(50, "lx_available")
def sys_lx_available(k, p):
    return k.linux.available()


@syscall(51, "lx_spawn")
def sys_lx_spawn(k, p, argv):
    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > 256:
        raise KError(EINVAL)
    try:
        return k.linux.spawn(p, [_str(a) for a in argv])
    except OSError as e:
        raise KError(e.errno or 2, str(e))


@syscall(52, "lx_read")
def sys_lx_read(k, p, h, n=4096):
    return k.linux.read(p, _int(h, 1), _int(n, 1, MAX_IO))


@syscall(53, "lx_write")
def sys_lx_write(k, p, h, data):
    return k.linux.write(p, _int(h, 1), _bytes(data))


@syscall(54, "lx_wait")
def sys_lx_wait(k, p, h, nohang=False):
    return k.linux.wait(p, _int(h, 1), bool(nohang))


@syscall(55, "lx_kill")
def sys_lx_kill(k, p, h):
    return k.linux.kill(p, _int(h, 1))


@syscall(56, "lx_close")
def sys_lx_close(k, p, h):
    return k.linux.close_stdin(p, _int(h, 1))


@syscall(57, "ttyctl")
def sys_ttyctl(k, p, op, arg=None):
    """Control de la consola: raw on/off, lectura sin bloqueo, tamaño en celdas."""
    op = _str(op, 16)
    if op == "raw":
        k.tty.set_raw(p.pid, bool(arg), isig=(arg != "nosig"))
        return 0
    if op == "fg":
        return sorted(k.tty.fg)
    if op == "read":
        if k.tty.raw_owner != p.pid:
            raise KError(EINVAL, "la consola no está en modo crudo")
        return k.tty.read_nowait(_int(1 if arg is None else arg, 1, MAX_IO))
    if op == "size":
        return p.winsize if p.winsize is not None else k.tty.size()
    if op == "winsize":
        # Tamaño de terminal virtual (ventana de LOOK) que heredan los hijos de este proceso.
        if arg is None:
            p.winsize = None
            return 0
        if not isinstance(arg, (tuple, list)) or len(arg) != 2:
            raise KError(EINVAL)
        p.winsize = (_int(arg[0], 10, 1000), _int(arg[1], 5, 1000))
        return 0
    raise KError(EINVAL)


@syscall(58, "gfx_open")
def sys_gfx_open(k, p):
    return k.gfx.open(p)


@syscall(59, "gfx_draw")
def sys_gfx_draw(k, p, cmds):
    return k.gfx.draw(p, cmds)


@syscall(60, "gfx_poll")
def sys_gfx_poll(k, p, timeout_ms=0):
    return k.gfx.poll(p, _int(timeout_ms, 0, 3600000))


@syscall(61, "gfx_close")
def sys_gfx_close(k, p):
    k.gfx._check_owner(p)
    k.gfx.close(p.pid)
    return 0


@syscall(62, "gfx_cursor")
def sys_gfx_cursor(k, p, visible=None, x=None, y=None):
    return k.gfx.set_cursor(p, visible, None if x is None else (x, y))


@syscall(63, "fdctl")
def sys_fdctl(k, p, fd, op, arg=None):
    """Opciones de un descriptor: 'nonblock' (True/False)."""
    from .fs.vfs import O_NONBLOCK
    of = _fd(p, fd)
    op = _str(op, 16)
    if op == "nonblock":
        if arg:
            of.flags |= O_NONBLOCK
        else:
            of.flags &= ~O_NONBLOCK
        return 0
    raise KError(EINVAL)


def _net(k):
    if k.net is None:
        raise KError(19, "no hay red")
    return k.net


@syscall(64, "net_info")
def sys_net_info(k, p):
    if k.net is None:
        return {"available": False, "reason": getattr(k.m, "nic_error", "") or "sin tarjeta de red soportada"}
    return k.net.info()


@syscall(65, "net_config")
def sys_net_config(k, p, spec):
    n = _net(k)
    spec = _str(spec, 128)
    if spec == "dhcp":
        n.stack.dhcp_start()
    else:
        n.config_static(spec)
    return 0


@syscall(66, "socket")
def sys_socket(k, p, kind="tcp"):
    from .fs.vfs import O_RDWR
    sf = _net(k).socket(p, _str(kind, 8))
    of = OpenFile(sf, O_RDWR, "socket:[%s]" % kind)
    fd = p.alloc_fd(of, 0, MAX_FD)
    if fd < 0:
        sf.close(of)
        raise KError(EMFILE)
    return fd


@syscall(67, "connect")
def sys_connect(k, p, fd, ip, port):
    return _net(k).connect(p, _fd(p, fd), _str(ip, 64), _int(port, 1, 65535))


@syscall(68, "bind")
def sys_bind(k, p, fd, port):
    return _net(k).bind(p, _fd(p, fd), _int(port, 0, 65535))


@syscall(69, "listen")
def sys_listen(k, p, fd, backlog=5):
    return _net(k).listen(p, _fd(p, fd), _int(backlog, 1, 64))


@syscall(70, "accept")
def sys_accept(k, p, fd):
    from .fs.vfs import O_RDWR
    sf, addr = _net(k).accept(p, _fd(p, fd))
    of = OpenFile(sf, O_RDWR, "socket:[tcp]")
    nfd = p.alloc_fd(of, 0, MAX_FD)
    if nfd < 0:
        sf.close(of)
        raise KError(EMFILE)
    return (nfd, addr[0], addr[1])


@syscall(71, "sendto")
def sys_sendto(k, p, fd, data, ip, port):
    from .net.pkt import s2ip
    n = _net(k)
    s = n.sock_of(_fd(p, fd))
    try:
        addr = (s2ip(_str(ip, 64)), _int(port, 1, 65535))
    except ValueError:
        raise KError(EINVAL)
    return n.sendto(s, _bytes(data), addr)


@syscall(72, "recvfrom")
def sys_recvfrom(k, p, fd, n=65536):
    return _net(k).recvfrom(p, _fd(p, fd), _int(n, 1, MAX_IO))


@syscall(73, "ping")
def sys_ping(k, p, ip, ident, seq, timeout_ms=2000):
    return _net(k).ping(p, _str(ip, 64), _int(ident, 0, 65535), _int(seq, 0, 65535),
                        _int(timeout_ms, 1, 60000))


@syscall(74, "resolve")
def sys_resolve(k, p, name):
    return _net(k).resolve(p, _str(name, 253))


@syscall(75, "exctb")
def sys_exctb(k, p, exc):
    """Traceback de PVM de una excepción capturada por el programa: [(fichero, línea, función)],
    del marco más interno al más externo. Solo lee lo que la propia PVM anotó."""
    if not isinstance(exc, BaseException):
        raise KError(EINVAL)
    tb = getattr(exc, "_pvm_tb", None) or []
    return [(str(f), int(l), str(n)) for f, l, n in tb[:32]]


@syscall(76, "klog")
def sys_klog(k, p, msg):
    """Una línea de un programa en el log del kernel (como escribir en /dev/kmsg)."""
    text = _str(msg, 400).replace("\n", " ")
    k.log("%s[%d]: %s" % (p.name, p.pid, text))
    return 0


@syscall(45, "reboot")
def sys_reboot(k, p, cmd):
    if _str(cmd) not in ("poweroff", "reboot"):
        raise KError(EINVAL)
    k.request_halt(cmd)
    return 0
