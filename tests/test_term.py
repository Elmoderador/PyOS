"""PyOS Term: modos de arranque, paquetes, servicios, dispositivos y subsistema Linux."""
import shutil

import pytest

from pyos.__main__ import run_machine
from pyos.boot import firmware
from pyos.hal.emulated import Raw, ScriptConsole
from pyos.tools import mkimage

MEM = 16 << 20


@pytest.fixture
def image(tmp_path):
    p = str(tmp_path / "pyos.img")
    mkimage.build(p, size_mb=8)
    return p


def boot(image, steps, mode="term", linux=False, timeout=30):
    con = ScriptConsole(steps, timeout=timeout)
    rc = run_machine(image, MEM, lambda: con, max_reboots=1, mode=mode, linux=linux)
    return rc, con.transcript


def test_modo_term_y_look_sin_instalar(image):
    rc, out = boot(image, ["cat /proc/cmdline", "halt"])
    assert "mode=term" in out and "PyOS Term — 'help'" in out
    rc, out = boot(image, ["pyos look", "pkg remove look", "pyos look", "halt"])
    assert "PyOS LOOK instalado: ejecuta 'look'" in out
    assert "desinstalado look" in out and "PyOS LOOK no está instalado: pkg install look" in out
    assert rc == firmware.EXIT_HALT


def test_formato_de_paquete():
    blob = mkimage.pack({"name": "x", "version": "1"}, {"/bin/a.py": b"print(1)\n", "/b": b""})
    assert blob.startswith(b"PYOSPKG 1\n") and blob.endswith(b"end\n")
    assert b"file /bin/a.py 9\nprint(1)\n\n" in blob
    pk = mkimage.build_packages()
    assert "extras-1.0.0.pkg" in pk and "juegos-1.0.0.pkg" in pk


def test_pkg_instala_dependencias_usa_y_desinstala(image):
    rc, out = boot(image, [
        "pkg avail", "pkg install juegos", "pkg list",
        "echo b > /tmp/l", "echo a >> /tmp/l", "echo b >> /tmp/l",
        "sort /tmp/l | uniq -c", "tree /etc", "find / -name *.svc",
        "pkg verify extras", "pkg remove extras", "pkg remove juegos", "pkg remove extras",
        "sort /tmp/l", "pkg install /tmp/nada.pkg", "halt"])
    assert "instalando dependencia extras" in out
    assert "instalado extras 1.0.0 (5 ficheros)" in out and "instalado juegos 1.0.0 (2 ficheros)" in out
    assert "      1 a\n      2 b" in out
    assert "└── svc/" in out and "/etc/svc/logd.svc" in out
    assert "extras: 5 ficheros, 0 con diferencias" in out
    assert "extras lo necesita juegos" in out and "desinstalado juegos" in out
    assert "desinstalado extras" in out and "sort: orden no encontrada" in out or "no encontr" in out
    assert rc == firmware.EXIT_HALT


def test_pkg_rechaza_paquetes_maliciosos(image):
    rc, out = boot(image, [
        "write /tmp/evil.pkg PYOSPKG 1",
        "pkg install /tmp/evil.pkg", "halt"])
    assert "paquete inválido" in out


def test_servicios(image):
    rc, out = boot(image, [
        "svc list", "sleep 2.5", "cat /var/log/kernel.log", "svc stop logd", "svc list",
        "svc disable logd", "svc start logd", "svc start logd", "cat /etc/svc/enabled", "halt"])
    assert "svc: logd arrancado" in out
    assert "activo:" in out and "parado" in out
    assert "PyOS 1.0.0" in out or "kernel" in out                 # el log del kernel llegó al fichero
    assert "deshabilitado en el arranque" in out and "ya está en marcha" in out
    rc, out = boot(image, ["svc list", "halt"])
    assert "svc: logd arrancado" not in out                   # persistió el 'disable'


def test_dispositivos_y_admin(image):
    rc, out = boot(image, ["dev", "dev kbd", "dev irq", "pyos", "pyos version", "pyos dev pci", "halt"])
    assert "tty" in out and "no hay teclado PS/2" in out and "timer" in out
    assert "PyOS 1.0.0" in out and "linux: no disponible" in out and "logd" in out
    assert "(sin bus PCI)" in out


def test_lx_sin_kernel_linux(image):
    rc, out = boot(image, ["lx", "lx uname", "cat /proc/linux", "halt"])
    assert "subsistema Linux no disponible" in out and "no hay kernel Linux" in out


@pytest.mark.skipif(shutil.which("sh") is None, reason="host sin /bin/sh")
def test_lx_ejecuta_procesos_linux_reales(image):
    rc, out = boot(image, [
        "lx", "lx uname -s", "lx sh -c 'echo $((6*7)); exit 3'", "lx printf 'b\\na\\n' | wc",
        "lx -i cat", Raw(b"hola linux\r", 0.5), Raw(b"\x04", 0.5), "lx no-existe-xyz", "halt"], linux=True)
    assert "subsistema Linux:" in out and "Linux\n" in out
    assert "42" in out
    assert "2 2 4" in out                                        # tubería Linux -> PyOS
    assert out.count("hola linux") >= 2                        # eco de la consola + salida de cat
    assert "lx: " in out and "no-existe-xyz" in out
    assert rc == firmware.EXIT_HALT
