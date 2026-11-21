import builtins
import re
from pathlib import Path

import pytest

from pyos.kernel import syscalls
from pyos.kernel.cpu.compiler import CompileError, compile_source
from pyos.kernel.proc.loader import build_builtins
from pyos.kernel.cpu.vm import PVM, Frame, SyscallGate, R_BUDGET, R_ERROR, R_EXIT, R_SYSCALL, fork_state
from tests.pvm_cases import CASES
from tests.pvm_check import run_cpython, run_pvm

LIBPY = Path(__file__).resolve().parent.parent / "pyos" / "userland" / "lib" / "libpy.py"
USERLAND = LIBPY.parent.parent


@pytest.mark.parametrize("name", sorted(CASES))
def test_pvm_equivale_a_cpython(name):
    got, slices = run_pvm(CASES[name], budget=13)   # rodajas diminutas: máxima apropiación
    assert got == run_cpython(CASES[name])


def _vm(src):
    code = compile_source(src, "<t>")
    g = {}
    gate = SyscallGate(1)
    g["syscall"] = gate
    vm = PVM(build_builtins(), gate)
    vm.frames.append(Frame(code, g))
    return vm, g


def test_syscall_es_una_trampa_y_reanuda():
    vm, g = _vm("a = syscall(42, 'x') + 1\nb = syscall(7)")
    assert vm.run(10000) == (R_SYSCALL, (42, "x"))
    vm.resume_with(99)
    assert vm.run(10000) == (R_SYSCALL, (7,))
    vm.resume_with("ok")
    assert vm.run(10000)[0] == R_EXIT
    assert g["a"] == 100 and g["b"] == "ok"


def test_fork_copia_estado_completo():
    vm, g = _vm("def gen():\n    n = 0\n    while True:\n        n += 1\n        yield n\n"
                "it = gen()\nnext(it)\nd = [1]\nr = syscall(8)\nd.append(r)\nv = next(it)")
    assert vm.run(10000)[0] == R_SYSCALL
    child, (cg,) = fork_state(vm, SyscallGate(2), [g])
    vm.resume_with(123)
    child.resume_with(0)
    assert vm.run(10000)[0] == R_EXIT and child.run(10000)[0] == R_EXIT
    assert g["d"] == [1, 123] and cg["d"] == [1, 0]
    assert g["v"] == 2 and cg["v"] == 2          # el generador se copió en su estado


@pytest.mark.parametrize("src", [
    "x = ().__class__", "def f():\n    yield 1\nx = f().gi_frame", "x = syscall.pid",
    "x = (lambda: 0).code", "x = __import__('os')", "x = eval('1')",
    "x = type(syscall)(5)", "x = type(len).mro", "x = ValueError().__traceback__",
    # Base.__init__ solo se permite si es código de la PVM: nunca métodos del host
    "x = int.__init__", "class A:\n    pass\nx = A.__init__", "class A:\n    pass\nx = A.__subclasses__",
    "class A:\n    def __init__(self):\n        pass\nx = A().__init__",
    "class A(Exception):\n    pass\nx = A.__init__",
])
def test_escapes_bloqueados(src):
    vm, g = _vm(src)
    code, val = vm.run(10000)
    assert code == R_ERROR and "x" not in g


def test_llamar_al_init_de_la_clase_base():
    vm, g = _vm("class A:\n    def __init__(self, v):\n        self.v = v\n"
                "class B(A):\n    def __init__(self):\n        A.__init__(self, 7)\n        self.w = 1\n"
                "b = B()\nx = (b.v, b.w)\n")
    code, val = vm.run(10000)
    assert code == R_EXIT and g["x"] == (7, 1)


@pytest.mark.parametrize("src", ["import os", "async def f():\n    pass", "nonlocal x"])
def test_compilador_rechaza(src):
    with pytest.raises(CompileError):
        compile_source(src, "<t>")


def test_todo_el_userland_compila():
    paths = list(USERLAND.rglob("*.py")) + list((USERLAND.parent / "packages").rglob("*.py"))
    for path in paths:
        compile_source(path.read_text(encoding="utf-8"), str(path))


def test_numeros_de_syscall_coinciden_con_libpy():
    src = LIBPY.read_text(encoding="utf-8")
    user = {}
    for names, nums in re.findall(r"^(SYS_[A-Z0-9_, ]+?)\s*=\s*([\d, ]+)$", src, re.M):
        for n, v in zip(names.split(","), nums.split(",")):
            user[n.strip()[4:].lower()] = int(v)
    kernel = dict((name, num) for num, (name, _) in syscalls.build_table().items())
    assert user == kernel


@pytest.mark.parametrize("exc", ["KeyboardInterrupt", "SystemExit", "GeneratorExit"])
def test_baseexception_de_usuario_no_escapa_de_la_pvm(exc):
    vm, g = _vm("x = 1\nraise %s()" % exc)
    vm.builtins[exc] = getattr(builtins, exc)
    code, val = vm.run(10000)
    assert code == R_ERROR and type(val.exc).__name__ == exc


def test_keyboardinterrupt_capturable_por_el_usuario():
    vm, g = _vm("try:\n    raise KeyboardInterrupt()\nexcept KeyboardInterrupt:\n    ok = True")
    assert vm.run(10000)[0] == R_EXIT and g["ok"] is True
