# /bin/rmdir
def main(argv):
    rc = 0
    for p in argv[1:]:
        try:
            rmdir(p)
        except OSError as e:
            eprint("rmdir: " + p + ": " + e.args[1])
            rc = 1
    return rc
