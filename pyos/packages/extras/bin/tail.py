# tail [-n N] [fichero] — últimas líneas
def main(argv):
    n = 10
    files = []
    i = 1
    while i < len(argv):
        if argv[i] == "-n" and i + 1 < len(argv):
            n = int(argv[i + 1])
            i += 2
            continue
        files.append(argv[i])
        i += 1
    data = read_file(files[0]).decode() if files else read_all(STDIN).decode()
    for l in data.splitlines()[-n:] if n > 0 else []:
        print(l)
