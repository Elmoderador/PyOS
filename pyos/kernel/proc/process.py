"""Descriptor de proceso, señales y colas de espera (sin hilos)."""

NEW, READY, RUNNING, BLOCKED, ZOMBIE = "new", "ready", "running", "blocked", "zombie"

SIGINT, SIGKILL, SIGSEGV, SIGPIPE, SIGTERM, SIGCHLD = 2, 9, 11, 13, 15, 17
SIGNAL_NAMES = {SIGINT: "SIGINT", SIGKILL: "SIGKILL", SIGSEGV: "SIGSEGV",
                SIGPIPE: "SIGPIPE", SIGTERM: "SIGTERM", SIGCHLD: "SIGCHLD"}
CATCHABLE = (SIGINT, SIGTERM, SIGPIPE, SIGCHLD)
IGNORED_BY_DEFAULT = (SIGCHLD,)


class Block(Exception):
    """Lanzada por una syscall que debe esperar. Se reintenta al despertar."""

    def __init__(self, wq, deadline=None):
        Exception.__init__(self)
        self.wq, self.deadline = wq, deadline


class ProcessExit(Exception):
    def __init__(self, status):
        Exception.__init__(self)
        self.status = status


class Process(object):
    def __init__(self, pid, parent, name, argv=None, cwd="/"):
        self.pid = pid
        self.parent = parent
        self.ppid = parent.pid if parent else 0
        self.name = name
        self.argv = list(argv or [name])
        self.cwd = cwd
        self.winsize = parent.winsize if parent is not None else None   # terminal virtual (LOOK)
        self.state = NEW
        self.exit_status = None
        self.aspace = None
        self.vm = None                 # PVM: el estado de CPU del proceso
        self.fds = {}
        self.children = []
        self.pending_signals = []
        self.sighandlers = {}          # sig -> VMFunction | "ignore"
        self.pending_syscall = None    # syscall pendiente de reintentar
        self.wait_channel = ""
        self.wq = None
        self.cpu_ticks = 0
        self.instructions = 0
        self.syscalls = 0
        self.start_tick = 0
        self.deadline = None
        self.child_wq = None
        self.image = ""

    def alloc_fd(self, ofile, lowest=0, limit=64):
        for fd in range(lowest, limit):
            if fd not in self.fds:
                self.fds[fd] = ofile
                return fd
        return -1

    def __repr__(self):
        return "<Process %d %s %s>" % (self.pid, self.name, self.state)


class WaitQueue(object):
    def __init__(self, kernel, name):
        self.kernel = kernel
        self.name = name
        self.waiters = []

    def add(self, proc):
        if proc not in self.waiters:
            self.waiters.append(proc)

    def remove(self, proc):
        if proc in self.waiters:
            self.waiters.remove(proc)

    def wake_all(self):
        waiters, self.waiters = self.waiters, []
        for p in waiters:
            self.kernel.wake(p)
