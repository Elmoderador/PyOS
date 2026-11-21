# /bin/rm
def remove(p, recursive):
    st = stat(p)
    if st["type"] == "dir":
        if not recursive:
            raise OSError(21, "Is a directory (usa -r)")
        for name, typ in listdir(p):
            remove(p.rstrip("/") + "/" + name, True)
        rmdir(p)
    else:
        unlink(p)


def main(argv):
    rec = "-r" in argv
    rc = 0
    for p in [a for a in argv[1:] if a != "-r"]:
        try:
            remove(p, rec)
        except OSError as e:
            eprint("rm: " + p + ": " + e.args[1])
            rc = 1
    return rc
