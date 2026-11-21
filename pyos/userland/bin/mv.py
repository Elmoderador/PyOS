# /bin/mv
def main(argv):
    if len(argv) != 3:
        eprint("uso: mv ORIGEN DESTINO")
        return 2
    try:
        rename(argv[1], argv[2])
    except OSError as e:
        eprint("mv: " + e.args[1])
        return 1
