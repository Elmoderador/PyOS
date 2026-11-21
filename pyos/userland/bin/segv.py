# /bin/segv
# segv: provoca violaciones de segmento a propósito.
def main(argv):
    what = argv[1] if len(argv) > 1 else "null"
    if what == "ro":
        m = mmap(4096, PROT_READ)
        poke(m, b"x")
    elif what == "kernel":
        peek(0xC0000000, 4)
    else:
        peek(0, 4)
    print("no debería llegar aquí")
