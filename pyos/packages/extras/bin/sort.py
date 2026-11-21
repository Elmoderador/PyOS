# sort [-r] [-n] [fichero] — ordena líneas
def main(argv):
    rev = "-r" in argv
    num = "-n" in argv
    files = [a for a in argv[1:] if not a.startswith("-")]
    data = read_file(files[0]).decode() if files else read_all(STDIN).decode()
    lines = data.splitlines()

    def key(l):
        if not num:
            return (0, l)
        try:
            return (0, float(l.split()[0]))
        except (ValueError, IndexError):
            return (1, l)
    for l in sorted(lines, key=key, reverse=rev):
        print(l)
