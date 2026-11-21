"""Planificador round-robin apropiativo sobre la PVM.

Cada proceso ejecuta rodajas de instrucciones; entre rodaja y rodaja el kernel
atiende las interrupciones (fronteras de instrucción). El temporizador (IRQ0)
descuenta el quantum del proceso actual; al agotarse, se expulsa de la CPU.
"""
from collections import deque

from .process import READY


class Scheduler(object):
    def __init__(self, quantum):
        self.quantum = quantum
        self.runq = deque()
        self.current = None
        self.need_resched = False
        self.slice_left = quantum
        self.switches = 0
        self.ticks = 0
        self.idle_ticks = 0

    def add(self, proc):
        proc.state = READY
        if proc not in self.runq:
            self.runq.append(proc)

    def remove(self, proc):
        try:
            self.runq.remove(proc)
        except ValueError:
            pass

    def tick(self):
        self.ticks += 1
        cur = self.current
        if cur is None:
            self.idle_ticks += 1
            return
        cur.cpu_ticks += 1
        self.slice_left -= 1
        if self.slice_left <= 0:
            self.need_resched = True

    def pick(self):
        """Siguiente proceso listo (round-robin) o None (CPU ociosa)."""
        if not self.runq:
            return None
        p = self.runq.popleft()
        if p is not self.current:
            self.switches += 1
            self.slice_left = self.quantum
        self.need_resched = False
        self.current = p
        return p
