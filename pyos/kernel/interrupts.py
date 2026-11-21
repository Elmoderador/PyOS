"""Gestión de interrupciones: IDT de 256 vectores y controlador de IRQs sondeado.

Sin manejadores de interrupción en ensamblador no se puede recibir una IRQ
asíncrona de la CPU. PyOS hace lo mismo que un kernel en modo "polling": en
cada frontera de rodaja (cada N instrucciones de la PVM) consulta los
registros de estado de los dispositivos (temporizador ACPI, i8042, UART,
PM1_STS) y despacha por la IDT los vectores de las líneas activas.
"""
from .errors import KernelPanic

VEC_PAGE_FAULT = 14
IRQ_BASE = 32
VEC_SYSCALL = 0x80


class IDT(object):
    def __init__(self):
        self.handlers = [None] * 256
        self.names = [None] * 256
        self.counts = [0] * 256

    def set_gate(self, vector, handler, name):
        self.handlers[vector] = handler
        self.names[vector] = name

    def dispatch(self, vector, *args):
        self.counts[vector] += 1
        h = self.handlers[vector]
        if h is None:
            raise KernelPanic("interrupción %d sin manejador" % vector)
        return h(*args)


class InterruptController(object):
    def __init__(self, idt, log):
        self.idt = idt
        self.log = log
        self.enabled = False
        self.sources = []       # (irq, función de sondeo)
        self.polls = 0

    def request_irq(self, irq, handler, name, poll):
        self.idt.set_gate(IRQ_BASE + irq, handler, name)
        self.sources.append((irq, poll))
        self.sources.sort(key=lambda s: s[0])

    def sti(self):
        self.enabled = True

    def cli(self):
        self.enabled = False

    def service(self):
        if not self.enabled:
            return 0
        self.polls += 1
        n = 0
        for irq, poll in self.sources:
            if poll():
                self.idt.dispatch(IRQ_BASE + irq)
                n += 1
        return n

    def stats(self):
        return [(v, self.idt.names[v], self.idt.counts[v])
                for v in range(256) if self.idt.handlers[v] is not None]
