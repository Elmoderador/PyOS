# /bin/memtest
# memtest: ejercita sbrk/mmap/mprotect y la paginación bajo demanda.
def rss():
    for line in read_file("/proc/self/status").decode().splitlines():
        if line.startswith("VmRSS"):
            return line.split()[1]


def main(argv):
    print("RSS inicial: " + rss() + " kB")
    base = sbrk(1024 * 1024)
    print("heap reservado 1 MiB en " + hex(base) + ", RSS: " + rss() + " kB (aún sin tocar)")
    for i in range(0, 1024 * 1024, 4096):
        poke(base + i, (i // 4096).to_bytes(4, "little"))
    print("tras tocar 256 páginas, RSS: " + rss() + " kB")
    ok = all(int.from_bytes(peek(base + i, 4), "little") == i // 4096 for i in range(0, 1024 * 1024, 4096))
    print("verificación del patrón: " + ("OK" if ok else "FALLO"))
    m = mmap(8192)
    poke(m, b"hola mmap")
    print("mmap en " + hex(m) + ": " + peek(m, 9).decode())
    mprotect(m, 8192, PROT_READ)
    print("mprotect(PROT_READ) aplicado")
    sbrk(-1024 * 1024)
    print("heap liberado, RSS: " + rss() + " kB")
    print(read_file("/proc/self/maps").decode(), end="")
    return 0 if ok else 1
