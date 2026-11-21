# /sbin/dev — dispositivos y su configuración.
#   dev | dev list | dev pci | dev irq | dev kbd [es|us]
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        print("MAJ,MIN NOMBRE   DESCRIPCIÓN")
        print(read_file("/proc/devices").decode(), end="")
        info = hwinfo()
        for k in ("kbd", "uart", "timer"):
            if k in info:
                print("%-8s %s" % (k + ":", info[k]))
        return 0
    if cmd == "pci":
        print(read_file("/proc/pci").decode(), end="")
        return 0
    if cmd == "irq":
        print(read_file("/proc/interrupts").decode(), end="")
        return 0
    if cmd == "kbd":
        try:
            if len(argv) > 2:
                print("teclado: distribución '%s'" % kbdlayout(argv[2]))
            else:
                print("teclado: distribución actual '%s' (disponibles: es, us)" % kbdlayout())
        except OSError as e:
            if e.errno == 19:
                print("dev: no hay teclado PS/2 que configurar (consola serie o máquina emulada)")
            else:
                print("dev: %s" % e)
            return 1
        return 0
    print("uso: dev [list|pci|irq|kbd [es|us]]")
    return 2
