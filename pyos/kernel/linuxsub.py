"""Subsistema Linux: segundo modelo de ejecución de PyOS.

Disponible SOLO cuando PyOS se ejecuta sobre un kernel Linux (HAL emulada en un
host Linux). Los procesos Linux son procesos REALES del kernel Linux, con sus
propias interfaces y su propio sistema de archivos: no comparten memoria ni
ficheros con los procesos PVM. PyOS solo les abre un canal de E/S:

    proceso PVM (lx) --syscalls lx_*--> kernel PyOS --pipes--> proceso Linux real

Cuando PyOS arranca directamente sobre el firmware UEFI no hay kernel Linux y
el subsistema informa de que no está disponible.
"""
from .errors import KError, EBADF, EPERM
from .proc.process import Block, WaitQueue

ENODEV = 19


class LinuxSubsystem(object):
    def __init__(self, kernel, bridge):
        self.k = kernel
        self.bridge = bridge                 # None si no hay kernel Linux debajo
        self.owner = {}                      # handle -> pid PyOS propietario
        self.wq = WaitQueue(kernel, "linux")

    def available(self):
        if self.bridge is None:
            return {"available": False,
                    "reason": "PyOS se ejecuta directamente sobre el firmware: no hay kernel Linux. "
                              "Arranca una distribución desde el selector y ejecuta PyOS sobre ella."}
        info = dict(self.bridge.info())
        info["available"] = True
        return info

    def _check(self, p, h):
        if self.bridge is None:
            raise KError(ENODEV, "subsistema Linux no disponible")
        owner = self.owner.get(h)
        if owner is None:
            raise KError(EBADF)
        q = p
        while q is not None:               # el dueño o sus descendientes
            if q.pid == owner:
                return
            q = q.parent
        raise KError(EPERM)

    def spawn(self, p, argv):
        if self.bridge is None:
            raise KError(ENODEV, "subsistema Linux no disponible")
        h = self.bridge.spawn(argv)
        self.owner[h] = p.pid
        self.k.log("linux: pid PyOS %d lanzó proceso Linux %s (%s)"
                   % (p.pid, self.bridge.host_pid(h), " ".join(argv)), "debug")
        return h

    def read(self, p, h, n):
        self._check(p, h)
        data, eof = self.bridge.read(h, n)
        if data or eof:
            return data
        if p.pending_signals:
            from .errors import EINTR
            raise KError(EINTR)
        raise Block(self.wq)

    def write(self, p, h, data):
        self._check(p, h)
        return self.bridge.write(h, data)

    def close_stdin(self, p, h):
        self._check(p, h)
        self.bridge.close_stdin(h)
        return 0

    def wait(self, p, h, nohang=False):
        self._check(p, h)
        st = self.bridge.status(h)
        if st is not None:
            self.bridge.forget(h)
            self.owner.pop(h, None)
            return st
        if nohang:
            return -1
        if p.pending_signals:
            from .errors import EINTR
            raise KError(EINTR)
        raise Block(self.wq)

    def kill(self, p, h):
        self._check(p, h)
        self.bridge.kill(h)
        return 0

    def release(self, pid):
        """Al morir un proceso PyOS se matan sus procesos Linux."""
        for h, owner in list(self.owner.items()):
            if owner == pid and self.bridge is not None:
                self.bridge.kill(h)
                self.bridge.forget(h)
                self.owner.pop(h, None)

    def poll(self):
        """Fuente de 'IRQ': hay datos o terminaciones en algún proceso Linux."""
        return self.bridge is not None and self.bridge.poll()

    def interrupt(self):
        self.wq.wake_all()

    def listing(self):
        if self.bridge is None:
            return "subsistema Linux: no disponible (arranque nativo sobre UEFI)\n"
        lines = ["HANDLE  PID-LINUX  DUEÑO  ESTADO   ORDEN"]
        for h, owner in sorted(self.owner.items()):
            st = self.bridge.status(h)
            lines.append("%6d  %9s  %5d  %-7s  %s" % (
                h, self.bridge.host_pid(h), owner, "vivo" if st is None else "fin %d" % st,
                " ".join(self.bridge.argv(h))))
        return "\n".join(lines) + "\n"
