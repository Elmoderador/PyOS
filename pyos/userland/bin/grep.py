# /bin/grep
def main(argv):
    if len(argv) < 2:
        eprint("uso: grep PATRÓN [FICHERO]")
        return 2
    fd = open(argv[2]) if len(argv) > 2 else STDIN
    found = 1
    for line in lines(fd):
        if argv[1] in line:
            print(line, end="")
            found = 0
    return found
