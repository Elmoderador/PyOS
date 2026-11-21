"""Punto de entrada de PyOS sobre UEFI (lo ejecuta Python.efi desde startup.nsh).

    UEFI firmware -> UEFI Shell -> Python.efi -> este fichero
        -> HAL de hardware real -> BIOS PyOS -> bootloader PyOS -> kernel PyOS

No hay ningún sistema operativo por debajo: solo el firmware de la máquina.
"""
import sys
import traceback


def _base_dir():
    path = __file__ if "__file__" in globals() else sys.argv[0]
    for sep in ("\\", "/"):
        if sep in path:
            return path.rsplit(sep, 1)[0]
    return "."


BASE = _base_dir()
SEP = "\\" if "\\" in BASE else "/"
sys.path.insert(0, BASE)

RAM_MB = 16


def say(text):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def wait_key(machine):
    while True:
        sc = machine.kbd.read_scancode() if machine.kbd.present else None
        if sc is not None and not sc & 0x80:
            return
        if machine.uart.present and machine.uart.read_byte() is not None:
            return
        machine.clock()


def main():
    say("")
    say("PyOS: iniciando máquina sobre UEFI (sin sistema operativo)...")
    say("  - el firmware cede el teclado y el puerto serie a PyOS")
    from pyos.hal.uefi import Machine
    from pyos.boot import firmware

    machine = Machine(RAM_MB * 1024 * 1024, BASE + SEP + "disk.img", scratch_dir=BASE)
    while True:
        rc = firmware.power_on(machine)
        if rc == firmware.EXIT_REBOOT:
            continue
        if rc == firmware.EXIT_HALT:
            say("Apagando la máquina...")
            machine.power_off()
            return
        say("\nLa máquina PyOS se detuvo (código %d). Pulsa una tecla para reiniciar." % rc)
        wait_key(machine)
        machine.reset()
        return


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        say("\n*** Error en el arranque de PyOS:\n" + traceback.format_exc())
        try:
            import edk2
            edk2.system("connect -r")
        except Exception:
            pass
