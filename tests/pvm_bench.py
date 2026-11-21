"""Banco de pruebas de la PVM: instrucciones/segundo en cargas típicas.
    python tests/pvm_bench.py            (también con python3.6)"""
import sys
import time
sys.path.insert(0, ".")
from pyos.kernel.cpu.compiler import compile_source
from pyos.kernel.cpu.vm import PVM, Frame, SyscallGate, R_EXIT, R_BUDGET
from pyos.kernel.proc.loader import build_builtins

PROGRAMS = {
    "bucles": """
def fib(n):
    a, b = 0, 1
    for i in range(n):
        a, b = b, a + b
    return a
t = 0
for k in range(3000):
    t += fib(30) % 7
""",
    "llamadas": """
def f(x, y):
    return x * 2 + y
t = 0
i = 0
while i < 60000:
    t = f(i, t) % 1000003
    i += 1
""",
    "objetos": """
class P:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def mover(self, dx):
        self.x += dx
        return self.x + self.y
ps = [P(i, i * 2) for i in range(200)]
t = 0
for r in range(150):
    for p in ps:
        t += p.mover(1)
""",
    "cadenas": """
out = []
for i in range(20000):
    s = "linea %d" % i
    if s.endswith("7"):
        out.append(s.upper())
    d = {"a": i, "b": len(s)}
    out.append(str(d["b"]))
r = ",".join(out)
""",
}


def run(src):
    code = compile_source(src, "<bench>")
    g = {}
    gate = SyscallGate(1)
    g["syscall"] = gate
    vm = PVM(build_builtins(), gate)
    vm.frames.append(Frame(code, g))
    t0 = time.perf_counter()
    while True:
        r, v = vm.run(1000000)
        if r != R_BUDGET:
            break
    dt = time.perf_counter() - t0
    assert r == R_EXIT, (r, v)
    return vm.icount, dt


if __name__ == "__main__":
    tot_i = tot_t = 0
    for name, src in PROGRAMS.items():
        n, dt = run(src)
        tot_i += n
        tot_t += dt
        print("%-9s %9d instr  %6.3f s  %8.0f kinstr/s" % (name, n, dt, n / dt / 1000))
    print("%-9s %9d instr  %6.3f s  %8.0f kinstr/s" % ("TOTAL", tot_i, tot_t, tot_i / tot_t / 1000))
