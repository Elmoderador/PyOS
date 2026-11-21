"""Extremo a extremo: imagen real -> BIOS -> bootloader -> kernel -> shell (máquina emulada)."""
import pytest

from pyos.__main__ import run_machine
from pyos.boot import firmware
from pyos.hal.emulated import FileDisk, Raw, ScriptConsole
from pyos.tools import mkimage

MEM = 16 << 20


@pytest.fixture
def image(tmp_path):
    p = str(tmp_path / "pyos.img")
    mkimage.build(p, size_mb=8)
    return p


def boot(image, steps, timeout=30):
    con = ScriptConsole(steps, timeout=timeout)
    rc = run_machine(image, MEM, lambda: con, max_reboots=1)
    return rc, con.transcript


def test_arranque_shell_y_apagado(image):
    rc, out = boot(image, ["uname -a", "ls /bin", "halt"])
    assert rc == firmware.EXIT_HALT
    assert "SHA-256 OK" in out and "PyOS pyos 1.0.0" in out
    assert "sh.py" in out and "Sistema detenido" in out


def test_tuberias_redirecciones_y_persistencia(image):
    rc, out = boot(image, [
        "mkdir /home/oier", "echo uno > /home/oier/f", "echo dos >> /home/oier/f",
        "cat /home/oier/f | grep dos | wc", "cat < /home/oier/f", "halt"])
    assert rc == firmware.EXIT_HALT
    assert "1 1 4" in out and "uno\ndos" in out
    rc, out = boot(image, ["cat /home/oier/f", "halt"])
    assert "uno\ndos" in out


def test_apropiacion_kill_y_ctrl_c(image):
    rc, out = boot(image, ["spin &", "echo sigo-viva", "kill spin", "sleep 0.2", "spin",
                           Raw(b"\x03", 0.5), "echo despues", "halt"])
    assert "sigo-viva" in out and "terminado (Terminated)" in out
    assert "^C" in out and "Interrupt" in out and "despues" in out
    assert rc == firmware.EXIT_HALT


def test_fork_exec_y_senales(image):
    rc, out = boot(image, ["forktest", "sigtest", "halt"])
    assert "'texto': 'modificado por el hijo'" in out and "'texto': 'original'" in out
    assert "terminó con estado 7" in out and "soy el hijo tras exec()" in out
    assert "manejador: recibida señal 15" in out and "SIGINT ignorada; recibidas=[15]" in out
    assert "hijo: me llegó SIGTERM" in out


def test_memoria_fallos_y_aislamiento(image):
    rc, out = boot(image, ["memtest", "segv", "segv ro", "segv kernel", "crash", "sandbox",
                           "cat /proc/1/stack", "halt"])
    assert "verificación del patrón: OK" in out
    assert out.count("Segmentation fault") == 3
    assert "ZeroDivisionError" in out and '"/bin/crash.py", line 4' in out
    assert "PVM íntegra" in out and "[ESCAPE]" not in out
    assert "waitpid" in out


def test_procfs_dispositivos_y_editor(image):
    rc, out = boot(image, ["cat /proc/interrupts", "ls /dev", "hexdump /dev/hda 16", "top",
                           "edit /root/hola.py",
                           Raw(b"a\rdef main(argv):\r    print('creado con edit')\r.\rwq\r", 1.0),
                           "cat /root/hola.py", "halt"], timeout=30)
    assert "timer" in out and "syscall" in out and "page-fault" in out
    assert "|PYOSBOOT" in out and "pvm_instructions" in out
    assert "guardado: 2 líneas" in out and "print('creado con edit')" in out


def test_eof_en_consola_apaga_via_init(image):
    rc, out = boot(image, ["echo fin"])
    assert "init: la interfaz terminó" in out and rc == firmware.EXIT_HALT


def test_kernel_corrupto_no_arranca(image):
    d = FileDisk(image)
    sector = bytearray(d.read(2, 1))
    sector[100] ^= 0xFF
    d.write(2, bytes(sector))
    d.close()
    rc, out = boot(image, [], timeout=3)
    assert rc == firmware.EXIT_NOBOOT and "corrupta" in out


def test_disco_sin_firma(tmp_path):
    p = tmp_path / "vacio.img"
    p.write_bytes(bytes(1 << 20))
    con = ScriptConsole([], timeout=2)
    rc = run_machine(str(p), MEM, lambda: con, max_reboots=1)
    assert rc == firmware.EXIT_NOBOOT and "No bootable device" in con.transcript
