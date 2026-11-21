# /sbin/pyos — punto de entrada de la administración (PyOS Term).
#   pyos [status] | pkg ... | svc ... | dev ... | linux ... | look | version
TOOLS = {"pkg": "/sbin/pkg.py", "svc": "/sbin/svc.py", "dev": "/sbin/dev.py", "linux": "/bin/lx.py"}


def status():
    u = uname()
    print("%s %s — %s, máquina %s" % (u[0], u[2], u[3], u[4]))
    print("uptime: %d s" % (uptime_ms() // 1000))
    mem = read_file("/proc/meminfo").decode().splitlines()
    for line in mem[:3]:
        print("  " + line)
    st = statfs()
    print("disco: %d/%d bloques libres" % (st["free_blocks"], st["blocks"]))
    li = lx_available()
    print("linux: " + ("%s (%s)" % (li["distro"], li["kernel"]) if li.get("available") else "no disponible"))
    print("look:  " + ("instalado" if exists("/bin/look.py") else "no instalado"))
    print()
    waitpid(spawn("/sbin/svc.py", ["svc", "list"]))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd in ("-h", "--help", "help"):
        print("uso: pyos [status] | pkg … | svc … | dev … | linux … | look | version")
        return 0
    if cmd == "status":
        status()
        return 0
    if cmd == "version":
        print(read_file("/proc/version").decode(), end="")
        return 0
    if cmd in TOOLS:
        exec(TOOLS[cmd], [cmd] + argv[2:])
    if cmd == "look":
        if exists("/bin/look.py"):
            print("PyOS LOOK instalado: ejecuta 'look' o elige 'PyOS LOOK' en el selector de arranque.")
            print("Necesita un adaptador VBE (QEMU std-VGA, VirtualBox VBoxSVGA/VBoxVGA) y ratón PS/2.")
        else:
            print("PyOS LOOK no está instalado: pkg install look")
        return 0
    print("pyos: orden desconocida: " + cmd)
    return 2
