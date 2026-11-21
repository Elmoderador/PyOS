# /bin/cat
def main(argv):
    rc = 0
    for path in argv[1:] or ["-"]:
        try:
            fd = STDIN if path == "-" else open(path)
            while True:
                chunk = read(fd, 65536)
                if not chunk:
                    break
                write(STDOUT, chunk)
            if fd != STDIN:
                close(fd)
        except OSError as e:
            eprint("cat: " + path + ": " + e.args[1])
            rc = 1
    return rc
