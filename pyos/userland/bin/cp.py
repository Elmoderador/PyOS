# /bin/cp
def main(argv):
    if len(argv) != 3:
        eprint("uso: cp ORIGEN DESTINO")
        return 2
    try:
        write_file(argv[2], read_file(argv[1]))
    except OSError as e:
        eprint("cp: " + e.args[1])
        return 1
