# uniq [-c] [fichero] — elimina líneas repetidas consecutivas
def main(argv):
    count = "-c" in argv
    files = [a for a in argv[1:] if not a.startswith("-")]
    data = read_file(files[0]).decode() if files else read_all(STDIN).decode()
    prev = None
    n = 0
    for l in data.splitlines() + [None]:
        if l == prev:
            n += 1
            continue
        if prev is not None:
            print(("%7d %s" % (n, prev)) if count else prev)
        prev = l
        n = 1
