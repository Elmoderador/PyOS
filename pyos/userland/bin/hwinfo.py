# /bin/hwinfo — información del hardware tal como la ve el kernel.
def main(argv):
    info = hwinfo()
    for k in ("platform", "cpu", "timer", "firmware", "kbd", "uart"):
        if k in info:
            print("%-9s %s" % (k + ":", info[k]))
    pci = info.get("pci") or []
    if pci:
        print("PCI:")
        for line in pci:
            print("  " + line)
