"""Kernel de PyOS: un solo hilo, procesos sobre la CPU virtual PVM."""
import traceback

from . import syscalls
from .cpu.vm import (PVM, Frame, SyscallGate, GuestError, VMFunction, fork_state,
                     R_BUDGET, R_EXIT, R_ERROR, R_SYSCALL)
from .drivers.chardevs import DiskDevice, NullDevice, RandomDevice, ZeroDevice
from .drivers.devices import DeviceManager
from .drivers.ps2kbd import PS2Keyboard
from .drivers.tty import TTY
from .errors import (KError, KernelPanic, EACCES, EAGAIN, ECHILD, EINTR, ENOEXEC, ENOMEM)
from .fs.buffercache import BufferCache
from .fs.devfs import DevFS
from .fs.procfs import ProcFS
from .fs.pyfs import BLOCK, PyFS
from .fs.vfs import O_RDONLY, O_RDWR, VFS
from .interrupts import IDT, VEC_PAGE_FAULT, VEC_SYSCALL, InterruptController
from .klog import KernelLog
from .linuxsub import LinuxSubsystem
from .drivers.gfx import Gfx
from .net.kernelnet import KernelNet, NullNIC
from .mm.pmm import PAGE_SIZE, FrameAllocator, OutOfMemory
from .mm.vmm import PROT_EXEC, PROT_READ, TEXT_BASE, AddressSpace, MapError, SegmentationFault
from .proc.loader import Loader, build_builtins
from .proc.process import (BLOCKED, IGNORED_BY_DEFAULT, READY, RUNNING, SIGCHLD, SIGKILL,
                           SIGSEGV, ZOMBIE, Block, Process, ProcessExit, WaitQueue)
from .proc.scheduler import Scheduler

VERSION = "1.0.0"
MAX_PROCS = 64
LIBPY = "/lib/libpy.py"
SLICE_MIN = 300           # instrucciones PVM entre comprobaciones de interrupciones (mínimo)
POLLS_PER_TICK = 4        # objetivo: sondear el hardware ~4 veces por tick del reloj
HALT_TIMEOUT = 5.0
_EXECED = object()


def parse_cmdline(cmdline):
    out = {}
    for tok in cmdline.split():
        k, sep, v = tok.partition("=")
        out[k] = v if sep else True
    return out


class Kernel(object):
    def __init__(self, bootinfo):
        self.bi = bootinfo
        self.m = bootinfo.machine
        self.m.kernel = self            # referencia para depuración y pruebas
        self.args = parse_cmdline(bootinfo.cmdline)
        self.procs = {}
        self.timed = set()
        self.next_pid = 1
        self.current = None
        self.halt_cmd = None
        self.halt_deadline = None
        self.loader = Loader()
        self.builtins = build_builtins()
        self.sys_table = syscalls.build_table()
        self.forks = 0
        self.hz = int(self.args.get("hz", 100))
        self.t0 = self.m.clock()

    def clock(self):
        return self.m.clock() - self.t0

    def _screen(self, data):
        self.m.console.write(data.replace(b"\n", b"\r\n"))

    # ================================================================ arranque
    def run(self):
        try:
            self._boot()
            return self._main_loop()
        except KernelPanic as e:
            return self._panic_screen(str(e))
        except Exception:
            return self._panic_screen("excepción en el kernel:\n" + traceback.format_exc())

    def _boot(self):
        m = self.m
        self.log = KernelLog(self._screen, self.clock, quiet="quiet" in self.args)
        log = self.log
        info = m.info()
        log("PyOS %s - kernel en Python, procesos sobre CPU virtual PVM" % VERSION)
        log("plataforma: %s" % info.get("platform"))
        log("cpu: %s" % info.get("cpu"))
        log("cmdline: %s" % self.bi.cmdline)
        log("kernel: %d bytes sha256=%s" % (self.bi.kernel_size, self.bi.kernel_sha256[:16]))

        self.pmm = FrameAllocator(m.ram)
        log("mm: %d marcos de 4 KiB (%d KiB), %d reservados, bitmap en %#x"
            % (self.pmm.nframes, m.ram.size // 1024, self.pmm.reserved, 0x1000))

        self.idt = IDT()
        self.intc = InterruptController(self.idt, log)
        self.idt.set_gate(VEC_PAGE_FAULT, self._page_fault, "page-fault")
        self.idt.set_gate(VEC_SYSCALL, self._syscall_gate, "syscall")

        self.sched = Scheduler(int(self.args.get("quantum", 5)))
        self.sleep_wq = WaitQueue(self, "sleep")
        self.slice = SLICE_MIN
        self._insns_at_tick = 0
        log("sched: round-robin apropiativo, quantum=%d ticks, rodaja adaptativa (>= %d instrucciones)"
            % (self.sched.quantum, SLICE_MIN))

        self.devices = DeviceManager(log)
        self.tty = TTY(self, m.console, getattr(m, "uart", None))
        self.devices.register(self.tty)
        self.kbd = None
        if getattr(m, "kbd", None) is not None and m.kbd.present:
            self.kbd = PS2Keyboard(m.kbd, self.tty.feed, self._ctrl_alt_del,
                                   layout=str(self.args.get("kbd", "es")))
            self.devices.register(self.kbd)
        for dev in (NullDevice(), ZeroDevice(),
                    RandomDevice(m.random_bytes, "fuente de entropía de la plataforma"),
                    DiskDevice(m.disk)):
            self.devices.register(dev)

        self.period = 1.0 / self.hz
        self.next_tick = self.m.clock() + self.period
        log("timer: %s, %d Hz" % (info.get("timer"), self.hz))
        self.intc.request_irq(0, self._timer_irq, "timer", self._timer_pending)
        if self.kbd is not None:
            self.intc.request_irq(1, self.kbd.interrupt, "keyboard", lambda: True)
        if self.tty.uart is not None:
            self.intc.request_irq(4, self.tty.uart_interrupt, "uart", self.tty.uart.has_data)
        self.intc.request_irq(9, self._power_irq, "acpi-power", m.power_button_pressed)
        self.gfx = Gfx(self, m)
        self.intc.request_irq(12, self.gfx.interrupt, "ps2-mouse", self.gfx.irq_pending)
        self.tty.on_raw_input = self.gfx.notify
        nic = getattr(m, "nic", None)
        if nic is None or self.args.get("net", "dhcp") == "off":
            log("net: sin tarjeta de red (%s); solo loopback 127.0.0.1" % (
                getattr(m, "nic_error", "") or ("desactivada con net=off" if nic is not None
                                                 else "no hay tarjeta soportada")))
            nic = NullNIC()
        self.net = KernelNet(self, nic, self.args)
        self.intc.request_irq(10, self.net.interrupt, "net0", self.net.irq_pending)
        self.linux = LinuxSubsystem(self, getattr(m, "linux", None))
        if self.linux.bridge is not None:
            self.intc.request_irq(11, self.linux.interrupt, "linux-bridge", self.linux.poll)
            li = self.linux.available()
            log("linux: subsistema disponible (%s, %s)" % (li.get("distro"), li.get("kernel")))
        else:
            log("linux: subsistema no disponible (sin kernel Linux debajo)")

        nblocks = (m.disk.sectors - self.bi.fs_lba) * 512 // BLOCK
        self.bcache = BufferCache(m.disk, self.bi.fs_lba, BLOCK, nblocks)
        self.rootfs = PyFS(self.bcache, m.wall)
        if not self.rootfs.was_clean:
            log("pyfs: el volumen no se desmontó limpiamente, ejecutando fsck", "warn")
            log("fsck: %s" % self.rootfs.fsck(repair=True), "warn")
        st = self.rootfs.statfs()
        log("pyfs: montado / (%d/%d bloques libres)" % (st["free_blocks"], st["blocks"]))
        self.vfs = VFS()
        self.vfs.mount("/", self.rootfs)
        self.vfs.mount("/dev", DevFS(self.devices))
        self.vfs.mount("/proc", ProcFS(self))

        self.intc.sti()
        console = self.vfs.open("/dev/tty", O_RDWR)
        fds = {0: console, 1: console.dup(), 2: console.dup()}
        init = self.args.get("init", "/sbin/init.py")
        self.spawn(None, init, [init], fds)
        log("init: lanzado %s (pid 1)" % init)

    # ================================================================ bucle principal
    def _main_loop(self):
        sched = self.sched
        while True:
            self.intc.service()
            if self.halt_cmd:
                alive = [p for p in self.procs.values() if p.state != ZOMBIE]
                if not alive or self.clock() > self.halt_deadline:
                    if alive:
                        self.log("halt: %d procesos no terminaron a tiempo" % len(alive), "warn")
                    return self._shutdown()
            p = sched.pick()
            if p is None:
                self.current = None
                sched.current = None
                self.m.idle()
                continue
            self.current = p
            p.state = RUNNING
            self._run_process(p)
            if p.state == RUNNING:
                sched.add(p)

    def _run_process(self, p):
        # 1) reintento de una syscall bloqueada (puede devolver EINTR)
        if p.pending_syscall is not None:
            if not self._do_syscall(p, p.pending_syscall):
                return
        # 2) señales pendientes
        if p.pending_signals and self._deliver_signals(p):
            return
        # 3) ejecución hasta agotar el quantum
        sched = self.sched
        while True:
            code, val = p.vm.run(self.slice)
            self._insns_at_tick += self.slice if code == R_BUDGET else 0
            if code == R_BUDGET:
                self.intc.service()
                if p.pending_signals and self._deliver_signals(p):
                    return
                if sched.need_resched or self.halt_cmd:
                    return
                continue
            if code == R_SYSCALL:
                if not self._do_syscall(p, val):
                    return
                if p.pending_signals and self._deliver_signals(p):
                    return
                if sched.need_resched:
                    return
                continue
            if code == R_EXIT:
                if self._next_phase(p, val):
                    continue
                return
            if code == R_ERROR:
                self._report_crash(p, val)
                self._exit(p, 1)
                return

    def _next_phase(self, p, value):
        """Módulo de libpy -> módulo del programa -> main(argv) -> exit."""
        if p.phase == "module":
            p.phase = "main"
            main = p.globals.get("main")
            if isinstance(main, VMFunction):
                try:
                    p.vm.frames.append(p.vm.make_frame(main, [list(p.argv)], {}))
                except TypeError as e:
                    self._report_crash(p, GuestError(e, []))
                    self._exit(p, 1)
                    return False
                return True
            value = 0
        status = value if isinstance(value, int) and not isinstance(value, bool) else 0
        self._exit(p, status & 0xFF)
        return False

    # ================================================================ syscalls
    def _do_syscall(self, p, args):
        """Ejecuta la syscall atrapada. True = el proceso puede seguir corriendo."""
        p.pending_syscall = None
        p.syscalls += 1
        try:
            ret = self.idt.dispatch(VEC_SYSCALL, p, args)
        except Block as b:
            p.pending_syscall = args
            self._block(p, b.wq, b.deadline)
            return False
        except ProcessExit as e:
            self._exit(p, e.status)
            return False
        if p.state == ZOMBIE:
            return False
        if ret is _EXECED:
            return True
        p.vm.resume_with(ret)
        return True

    def _syscall_gate(self, p, args):
        if not args:
            return -syscalls.ENOSYS
        num, rest = args[0], args[1:]
        entry = self.sys_table.get(num) if type(num) is int else None
        if entry is None:
            return -syscalls.ENOSYS
        try:
            return entry[1](self, p, *rest)
        except (Block, ProcessExit, KernelPanic):
            raise
        except KError as e:
            return -e.errno
        except SegmentationFault as e:
            self.log("segfault: pid %d (%s): %s" % (p.pid, p.name, e), "warn")
            self.send_signal(p, SIGSEGV)
            return -syscalls.EFAULT
        except OutOfMemory:
            self.log("oom: memoria agotada, matando pid %d (%s)" % (p.pid, p.name), "err")
            self.send_signal(p, SIGKILL)
            return -ENOMEM
        except MapError:
            return -ENOMEM
        except (TypeError, ValueError, OverflowError):
            return -syscalls.EINVAL
        except Exception:
            self.log("Oops en syscall %s (pid %d):\n%s" % (entry[0], p.pid, traceback.format_exc()), "err")
            self.send_signal(p, SIGKILL)
            return -syscalls.EFAULT

    # ================================================================ bloqueo y señales
    def _block(self, p, wq, deadline=None):
        p.state = BLOCKED
        p.wq = wq
        p.wait_channel = wq.name
        p.deadline = deadline if deadline is not None else p.deadline
        if deadline is not None and wq is not self.sleep_wq:
            self.timed.add(p)                   # espera con plazo en otra cola (p. ej. ping)
        wq.add(p)
        self.sched.remove(p)

    def wake(self, p):
        if p.state == BLOCKED:
            if p.wq is not None:
                p.wq.remove(p)
            p.wq = None
            p.wait_channel = ""
            self.sched.add(p)

    def send_signal(self, p, sig):
        if p.state == ZOMBIE or p.pid == 0:
            return
        h = p.sighandlers.get(sig)
        if sig != SIGKILL and (h == "ignore" or (h is None and sig in IGNORED_BY_DEFAULT)):
            return
        if sig not in p.pending_signals:
            p.pending_signals.append(sig)
        if p.state == BLOCKED:
            self.wake(p)

    def _deliver_signals(self, p):
        """True si el proceso ha muerto."""
        while p.pending_signals:
            sig = SIGKILL if SIGKILL in p.pending_signals else p.pending_signals[0]
            p.pending_signals.remove(sig)
            h = p.sighandlers.get(sig)
            if sig == SIGKILL or h is None:
                if sig in IGNORED_BY_DEFAULT:
                    continue
                self._exit(p, 128 + sig)
                return True
            if h == "ignore":
                continue
            try:
                f = p.vm.make_frame(h, [sig], {})
            except TypeError:
                self._exit(p, 128 + sig)
                return True
            f.mode = "signal"
            p.vm.frames.append(f)
        return False

    # ================================================================ interrupciones
    def _timer_pending(self):
        return self.m.clock() >= self.next_tick

    def _timer_irq(self):
        now = self.m.clock()
        if self.sched.current is not None and self._insns_at_tick:
            # rodaja adaptativa: ~POLLS_PER_TICK sondeos de hardware por tick
            target = max(SLICE_MIN, self._insns_at_tick // POLLS_PER_TICK)
            self.slice = (self.slice * 3 + target) // 4
        self._insns_at_tick = 0
        n = 0
        while now >= self.next_tick and n < 50:
            self.sched.tick()
            self.next_tick += self.period
            n += 1
        if now >= self.next_tick:
            self.next_tick = now + self.period
        if self.net is not None:
            self.net.timer()
        if self.sleep_wq.waiters or self.timed:
            t = self.clock()
            for p in list(self.sleep_wq.waiters):
                if p.deadline is not None and p.deadline <= t:
                    self.wake(p)
            for p in list(self.timed):
                if p.state != BLOCKED or p.deadline is None:
                    self.timed.discard(p)
                elif p.deadline <= t:
                    self.timed.discard(p)
                    self.wake(p)

    def _power_irq(self):
        self.power_button()

    def power_button(self):
        if self.halt_cmd:
            self.log("acpi: segunda pulsación, apagado inmediato", "warn")
            self.halt_deadline = 0
            return
        self.log("acpi: botón de encendido pulsado", "warn")
        self.request_halt("poweroff")

    def _ctrl_alt_del(self):
        self.log("teclado: Ctrl+Alt+Supr", "warn")
        self.request_halt("reboot")

    def _page_fault(self, aspace, pf):
        aspace.handle_fault(pf)

    # ================================================================ procesos
    def _read_file(self, path, cwd="/"):
        st = self.vfs.stat(path, cwd)
        if st["type"] != "file":
            raise KError(EACCES, "no es un fichero regular")
        of = self.vfs.open(path, O_RDONLY, cwd)
        try:
            chunks = []
            while True:
                c = of.read(65536)
                if not c:
                    break
                chunks.append(c)
            return b"".join(chunks)
        finally:
            of.close()

    def _load_segment(self, aspace, base, image, name):
        aspace.map(base, max(len(image), 1), PROT_READ | PROT_EXEC, name)
        aspace.write(base, image, force=True)
        return aspace.read(base, len(image))

    def _load_image(self, p, path, argv):
        """Carga un programa en un proceso: nuevo espacio de direcciones y nueva PVM."""
        abspath = self.vfs.normalize(path, p.cwd)
        image = self._read_file(abspath)
        lib = self._read_file(LIBPY)
        aspace = AddressSpace(self.pmm)
        aspace.fault_handler = lambda pf: self.idt.dispatch(VEC_PAGE_FAULT, aspace, pf)
        try:
            text = self._load_segment(aspace, TEXT_BASE, image, abspath)
            libtext = self._load_segment(aspace, aspace.find_free(len(lib) or 1), lib, LIBPY)
            lib_code = self.loader.load(libtext, LIBPY)
            code = self.loader.load(text, abspath)
        except OutOfMemory:
            aspace.destroy()
            raise KError(ENOMEM)
        except KError as e:
            aspace.destroy()
            if e.errno == ENOEXEC:
                self.log("exec: rechazado %s" % e.args[1], "warn")
            raise
        except Exception:
            aspace.destroy()
            raise
        if p.aspace is not None:
            p.aspace.destroy()
        p.aspace = aspace
        gate = SyscallGate(p.pid)
        g = {"__name__": "__main__", "syscall": gate}
        vm = PVM(self.builtins, gate, self._nested_syscall(p))
        vm.frames.append(Frame(code, g))
        vm.frames.append(Frame(lib_code, g))
        p.vm = vm
        p.globals = g
        p.phase = "module"
        p.name = abspath.rsplit("/", 1)[-1]
        p.image = abspath
        p.argv = list(argv)
        p.sighandlers = {}

    def _nested_syscall(self, p):
        """Syscalls desde código de usuario invocado por el host (sin poder bloquear)."""
        def handler(args):
            try:
                return self.idt.dispatch(VEC_SYSCALL, p, args)
            except Block:
                return -EAGAIN
        return handler

    def _new_pid(self):
        pid = self.next_pid
        self.next_pid += 1
        return pid

    def spawn(self, parent, path, argv, fds, cwd="/"):
        if len([q for q in self.procs.values() if q.state != ZOMBIE]) >= MAX_PROCS:
            raise KError(EAGAIN, "demasiados procesos")
        if self.halt_cmd:
            raise KError(EAGAIN, "el sistema se está apagando")
        p = Process(self.next_pid, parent, path, argv, cwd)
        self._load_image(p, path, argv)
        self._new_pid()
        p.fds = fds
        p.child_wq = WaitQueue(self, "wait")
        p.start_tick = self.sched.ticks
        if parent is not None:
            parent.children.append(p)
        self.procs[p.pid] = p
        self.forks += 1
        self.sched.add(p)
        return p

    def fork(self, parent):
        if len([q for q in self.procs.values() if q.state != ZOMBIE]) >= MAX_PROCS:
            raise KError(EAGAIN)
        pid = self._new_pid()
        child = Process(pid, parent, parent.name, parent.argv, parent.cwd)
        try:
            child.aspace = parent.aspace.clone()
        except OutOfMemory:
            raise KError(ENOMEM)
        gate = SyscallGate(pid)
        child.vm, extra = fork_state(parent.vm, gate, [parent.globals, parent.sighandlers])
        child.vm.syscall_handler = self._nested_syscall(child)
        child.globals, child.sighandlers = extra
        child.aspace.fault_handler = lambda pf: self.idt.dispatch(VEC_PAGE_FAULT, child.aspace, pf)
        child.phase = parent.phase
        child.image = parent.image
        child.fds = dict((fd, of.dup()) for fd, of in parent.fds.items())
        child.child_wq = WaitQueue(self, "wait")
        child.start_tick = self.sched.ticks
        child.vm.resume_with(0)                 # en el hijo, fork() devuelve 0
        parent.children.append(child)
        self.procs[pid] = child
        self.forks += 1
        self.sched.add(child)
        return pid

    def exec(self, p, path, argv):
        self._load_image(p, path, argv)
        return _EXECED

    def _report_crash(self, p, ge):
        lines = ["Traceback (most recent call last):"]
        for fname, line, name in ge.tb:
            lines.append('  File "%s", line %s, in %s' % (fname, line, name))
        exc = ge.exc
        lines.append("%s: %s" % (type(exc).__name__, exc) if str(exc) else type(exc).__name__)
        of = p.fds.get(2)
        try:
            if of is not None:
                of.write(("\n".join(lines) + "\n").encode("utf-8", "replace"))
        except Exception:
            pass

    def _exit(self, p, status):
        if p.state == ZOMBIE:
            return
        for of in list(p.fds.values()):
            try:
                of.close()
            except KError:
                pass
        p.fds.clear()
        if p.aspace is not None:
            p.aspace.destroy()
            p.aspace = None
        p.vm = None
        p.pending_syscall = None
        if p.wq is not None:
            p.wq.remove(p)
        self.sched.remove(p)
        self.tty.fg.discard(p.pid)
        self.gfx.release(p.pid)
        self.tty.release(p.pid)
        self.linux.release(p.pid)
        p.exit_status = status
        p.state = ZOMBIE
        init = self.procs.get(1)
        if p.children:
            for c in p.children:
                c.parent = init if init is not p else None
                c.ppid = 1 if c.parent else 0
                if c.parent is not None:
                    init.children.append(c)
            p.children = []
            if init is not None and init is not p:
                init.child_wq.wake_all()
        if p.parent is not None:
            p.parent.child_wq.wake_all()
            self.send_signal(p.parent, SIGCHLD)
        else:
            self.procs.pop(p.pid, None)
        if p is self.current:
            self.current = None
        if p.pid == 1 and not self.halt_cmd:
            raise KernelPanic("init terminó inesperadamente (estado %d)" % status)

    def reap(self, parent, pid, nohang):
        cands = [c for c in parent.children if pid == -1 or c.pid == pid]
        if not cands:
            raise KError(ECHILD)
        for c in cands:
            if c.state == ZOMBIE:
                parent.children.remove(c)
                self.procs.pop(c.pid, None)
                return (c.pid, c.exit_status)
        if nohang:
            return (0, 0)
        if parent.pending_signals:
            raise KError(EINTR)
        raise Block(parent.child_wq)

    def sleep(self, p, ms):
        now = self.clock()
        if p.deadline is None:
            p.deadline = now + ms / 1000.0
        if now >= p.deadline:
            p.deadline = None
            return 0
        if p.pending_signals:
            p.deadline = None
            raise KError(EINTR)
        raise Block(self.sleep_wq, p.deadline)

    # ================================================================ apagado
    def request_halt(self, cmd):
        if self.halt_cmd:
            return
        self.halt_cmd = cmd
        self.halt_deadline = self.clock() + HALT_TIMEOUT
        self.log("halt: solicitado '%s', terminando procesos" % cmd, "warn")
        for p in list(self.procs.values()):
            self.send_signal(p, SIGKILL)

    def _shutdown(self):
        self.log("halt: sincronizando y desmontando sistemas de archivos", "warn")
        self.rootfs.unmount()
        self.m.disk.flush()
        self.intc.cli()
        if self.halt_cmd == "reboot":
            self.log("Reiniciando...", "warn")
            return 1
        self.log("Sistema detenido.", "warn")
        return 0

    def _panic_screen(self, msg):
        try:
            self.intc.cli()
        except Exception:
            pass
        text = "\n*** KERNEL PANIC: %s\n*** Sistema detenido.\n" % msg
        try:
            self.log.buf.append(text.strip())
        except AttributeError:
            pass
        self._screen(text.encode("utf-8", "replace"))
        return 2

    # ================================================================ /proc
    def proc_meminfo(self):
        pmm = self.pmm
        live = [p for p in self.procs.values() if p.aspace is not None]
        user = sum(p.aspace.rss for p in live) * PAGE_SIZE
        pts = sum(p.aspace.pt_pages for p in live) * PAGE_SIZE
        rows = [("MemTotal", pmm.total_bytes), ("MemFree", pmm.free_bytes),
                ("MemUsed", pmm.total_bytes - pmm.free_bytes), ("Reserved", pmm.reserved * PAGE_SIZE),
                ("UserPages", user), ("PageTables", pts),
                ("BufferCache", len(self.bcache._c) * BLOCK), ("Dirty", self.bcache.dirty_count * BLOCK)]
        return "".join("%-14s%10d kB\n" % (k + ":", v // 1024) for k, v in rows) + \
            "%-14s%10d\n%-14s%10d\n" % ("FrameAllocs:", pmm.allocs, "FrameFrees:", pmm.frees)

    def proc_uptime(self):
        return "%.2f %.2f\n" % (self.sched.ticks / float(self.hz), self.sched.idle_ticks / float(self.hz))

    def proc_interrupts(self):
        lines = ["%4s %10s  %s" % ("VEC", "COUNT", "NAME")]
        for vec, name, count in self.intc.stats():
            lines.append("%4d %10d  %s" % (vec, count, name))
        lines.append("sondeos: %d" % self.intc.polls)
        return "\n".join(lines) + "\n"

    def proc_mounts(self):
        return "".join("%s %s %s rw 0 0\n" % (fs.name, mp, fs.name) for mp, fs in sorted(self.vfs.mounts.items()))

    def proc_devices(self):
        return "".join("%3d,%-3d %-8s %s\n" % (d.major, d.minor, d.name, d.description) for d in self.devices.all())

    def proc_version(self):
        import sys
        return "PyOS %s (CPython %s, %s) kernel-sha256 %s\n" % (
            VERSION, sys.version.split()[0], self.m.kind, self.bi.kernel_sha256[:16])

    def proc_cmdline(self):
        return self.bi.cmdline + "\n"

    def proc_filesystems(self):
        return "pyfs\nnodev devfs\nnodev procfs\n"

    def proc_stat(self):
        insns = sum(p.vm.icount for p in self.procs.values() if p.vm is not None)
        return ("ctxt %d\nticks %d\nprocesses %d\nsyscalls %d\npagefaults %d\n"
                "pvm_instructions %d\ncode_cache %d/%d\n" % (
                    self.sched.switches, self.sched.ticks, self.forks, self.idt.counts[VEC_SYSCALL],
                    self.idt.counts[VEC_PAGE_FAULT], insns, self.loader.hits, self.loader.misses))

    def proc_cpuinfo(self):
        info = self.m.info()
        keys = ("platform", "cpu", "timer", "firmware", "kbd", "uart")
        out = "".join("%-10s: %s\n" % (k, info[k]) for k in keys if k in info)
        return out + "pvm       : CPU virtual de PyOS, ISA de pila, apropiación por instrucciones\n"

    def proc_net(self):
        return self.net.proc_text()

    def proc_gfx(self):
        return self.gfx.proc_text()

    def proc_linux(self):
        return self.linux.listing()

    def proc_pci(self):
        return "".join(line + "\n" for line in self.m.info().get("pci", [])) or "(sin bus PCI)\n"

    def proc_process_file(self, p, what):
        a = p.aspace
        if what == "status":
            rss = a.rss * 4 if a else 0
            pts = a.pt_pages * 4 if a else 0
            insns = p.vm.icount if p.vm is not None else 0
            return ("Name:\t%s\nPid:\t%d\nPPid:\t%d\nState:\t%s\nWChan:\t%s\nCpuTicks:\t%d\n"
                    "Instructions:\t%d\nSyscalls:\t%d\nVmRSS:\t%d kB\nVmPTE:\t%d kB\nFaults:\t%d\n"
                    "Cwd:\t%s\nSignals:\t%s\n" % (
                        p.name, p.pid, p.ppid, p.state, p.wait_channel or "-", p.cpu_ticks, insns,
                        p.syscalls, rss, pts, a.faults if a else 0, p.cwd,
                        ",".join(str(s) for s in sorted(p.sighandlers)) or "-"))
        if what == "maps":
            return a.maps() if a else ""
        if what == "cmdline":
            return " ".join(p.argv) + "\n"
        if what == "fd":
            return "".join("%d %s\n" % (fd, of.path) for fd, of in sorted(p.fds.items()))
        if what == "stack":
            if p.vm is None:
                return ""
            out = []
            for f in p.vm.frames:
                pc = max(f.pc - 1, 0)
                line = f.code.lines[pc] if f.code.lines else 0
                out.append("%s:%d %s" % (f.code.filename, line, f.code.name))
            return "\n".join(reversed(out)) + "\n"
        raise KError(ENOEXEC)


def kernel_main(bootinfo):
    return Kernel(bootinfo).run()
