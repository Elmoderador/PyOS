"""Firmware de la máquina PyOS: POST, lectura del sector 0 y cesión al bootloader."""
import traceback

from . import bootloader, selector
from .bootrecord import BootRecordError

EXIT_HALT, EXIT_REBOOT, EXIT_PANIC, EXIT_NOBOOT, EXIT_POWER_CUT = 0, 1, 2, 3, 4


def post(machine):
    """Power-On Self Test: patrones en la primera y la última página de RAM."""
    ram = machine.ram
    for base in (0, ram.size - 4096):
        for pattern in (0x55, 0xAA):
            ram.fill(base, 4096, pattern)
            if ram.read(base, 4096) != bytes([pattern]) * 4096:
                raise RuntimeError("POST: fallo de RAM en %#x" % base)
        ram.fill(base, 4096, 0)


def power_on(machine, mode=None):
    """Enciende la máquina. mode: "term" | "look" | None (mostrar el selector)."""
    def say(text):
        machine.console.write(text.replace("\n", "\r\n").encode("utf-8"))

    say("PyOS BIOS v1.0 [%s]\n" % machine.kind)
    try:
        post(machine)
    except Exception as e:
        say("%s\n" % e)
        return EXIT_NOBOOT
    say("POST OK: %d KiB de RAM, disco de %d sectores\n" % (machine.ram.size // 1024, machine.disk.sectors))
    info = ""
    while mode is None:
        entries = selector.pyos_entries() + list(machine.boot_entries())
        choice = selector.choose(machine, entries, info)
        if choice.kind == "pyos":
            mode = choice.mode
            break
        say("\nArrancando %s (%s)...\n" % (choice.title, choice.loader))
        rc = machine.chainload(choice.loader)
        info = "No se pudo arrancar %s (estado %s)." % (choice.title, rc)
    say("Modo de arranque: PyOS %s\n" % ("LOOK" if mode == "look" else "Term"))
    try:
        return bootloader.boot(machine, machine.disk.read(0, 1), say, "mode=%s" % mode)
    except (BootRecordError, bootloader.BootError) as e:
        say("No bootable device: %s\n" % e)
        return EXIT_NOBOOT
    except KeyboardInterrupt:
        say("\n[corte de corriente]\n")
        return EXIT_POWER_CUT
    except BaseException:
        say("Triple fault:\n" + traceback.format_exc())
        return EXIT_PANIC
