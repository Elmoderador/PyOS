# /bin/mkdir
def main(argv):
    rc = 0
    for p in argv[1:]:
        try:
            mkdir(p)
        except OSError as e:
            eprint("mkdir: " + p + ": " + e.args[1])
            rc = 1
    return rc
