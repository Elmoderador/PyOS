"""CLI de PyOS:  python -m pyos {mkimage,update,fsck,run,mkuefi}"""
import argparse
import sys

from .boot import firmware
from .hal import emulated
from .tools import mkimage

RC_TEXT = {firmware.EXIT_HALT: "apagado", firmware.EXIT_REBOOT: "reinicio",
           firmware.EXIT_PANIC: "kernel panic", firmware.EXIT_NOBOOT: "sin dispositivo de arranque",
           firmware.EXIT_POWER_CUT: "corte de corriente"}


def parse_size(s):
    s = s.strip().upper()
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}.get(s[-1:], 1)
    return int(s[:-1] if s[-1:] in "KMG" else s) * mult


def run_machine(image, mem, console_factory, max_reboots=10, mode="term", linux=False):
    rc = firmware.EXIT_REBOOT
    for _ in range(max_reboots):
        console = console_factory()
        machine = emulated.Machine(mem, image, console, linux=linux)
        try:
            rc = firmware.power_on(machine, mode)
        finally:
            machine.shutdown()
        if rc != firmware.EXIT_REBOOT:
            break
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pyos")
    sub = ap.add_subparsers(dest="cmd")
    m = sub.add_parser("mkimage", help="crear una imagen de disco nueva")
    m.add_argument("image", nargs="?", default="pyos.img")
    m.add_argument("--size", type=int, default=32, help="MiB")
    m.add_argument("--cmdline", default=mkimage.DEFAULT_CMDLINE)
    u = sub.add_parser("update", help="reinstalar kernel y userland conservando datos")
    u.add_argument("image", nargs="?", default="pyos.img")
    u.add_argument("--cmdline")
    f = sub.add_parser("fsck", help="comprobar y reparar el FS de una imagen")
    f.add_argument("image", nargs="?", default="pyos.img")
    r = sub.add_parser("run", help="encender la máquina emulada")
    r.add_argument("image", nargs="?", default="pyos.img")
    r.add_argument("--mem", default="16M")
    r.add_argument("--script", help="fichero con órdenes a teclear (modo headless)")
    r.add_argument("--mode", choices=["term", "look", "menu"], default=None,
                   help="modo de arranque (por defecto: menú en interactivo, term con --script)")
    r.add_argument("--linux", action="store_true",
                   help="activar el subsistema Linux (solo si el host es Linux): los procesos "
                        "PyOS podrán ejecutar programas del host con 'lx'")
    a = ap.parse_args(argv)
    if a.cmd is None:
        ap.print_help()
        return 2
    if a.cmd == "mkimage":
        print(mkimage.build(a.image, a.size, a.cmdline))
        return 0
    if a.cmd == "update":
        print(mkimage.update(a.image, a.cmdline))
        return 0
    if a.cmd == "fsck":
        print(mkimage.fsck(a.image))
        return 0
    if a.script:
        with open(a.script, encoding="utf-8") as fh:
            steps = [ln.rstrip("\n") for ln in fh if ln.strip()]
        factory = lambda: emulated.ScriptConsole(steps, echo=True)  # noqa: E731
    else:
        factory = emulated.TerminalConsole
    try:
        mode = a.mode or ("term" if a.script else "menu")
        rc = run_machine(a.image, parse_size(a.mem), factory, mode=None if mode == "menu" else mode,
                         linux=a.linux)
    except KeyboardInterrupt:
        rc = firmware.EXIT_POWER_CUT
    msg = "\n[pyos] máquina detenida: %s\n" % RC_TEXT.get(rc, rc)
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        out.write(msg.encode("utf-8"))
        out.flush()
    else:
        print(msg)
    return 0 if rc == firmware.EXIT_HALT else rc


if __name__ == "__main__":
    sys.exit(main())
