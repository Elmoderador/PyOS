"""Compara la PVM con CPython. Uso: python tests/pvm_check.py  (funciona en 3.6 y 3.13)"""
import builtins
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pyos.kernel.cpu.compiler import compile_source  # noqa: E402
from pyos.kernel.cpu.vm import PVM, Frame, SyscallGate, R_EXIT, R_BUDGET, R_ERROR  # noqa: E402
from tests.pvm_cases import CASES  # noqa: E402


def run_pvm(src, budget=97):
    code = compile_source(src + "\nout = repr(out)\n", "<case>")
    g = {"__name__": "__main__"}
    b = dict(vars(builtins))
    vm = PVM(b, SyscallGate(1))
    vm.frames.append(Frame(code, g))
    slices = 0
    while True:
        r, v = vm.run(budget)          # presupuesto pequeño: fuerza miles de "cambios de contexto"
        slices += 1
        if r == R_EXIT:
            return g["out"], slices
        if r == R_ERROR:
            raise v.exc
        assert r == R_BUDGET, r


def run_cpython(src):
    g = {"__name__": "__main__"}
    exec(compile(src + "\nout = repr(out)\n", "<case>", "exec"), g)
    return g["out"]


def main():
    bad = 0
    for name, src in CASES.items():
        exp = run_cpython(src)
        try:
            got, slices = run_pvm(src)
        except Exception as e:
            import traceback
            traceback.print_exc()
            got, slices = "EXC %r" % e, 0
        ok = exp == got
        bad += not ok
        print("%-12s %s (%d rodajas)" % (name, "OK" if ok else "FALLO", slices))
        if not ok:
            print("  CPython:", exp)
            print("  PVM:    ", got)
    print("RESULTADO:", "OK" if not bad else "%d fallos" % bad)
    return bad


if __name__ == "__main__":
    sys.exit(main())
