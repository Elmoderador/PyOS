# /bin/ls
def main(argv):
    longfmt = "-l" in argv
    paths = [a for a in argv[1:] if not a.startswith("-")] or ["."]
    rc = 0
    for path in paths:
        try:
            st = stat(path)
            entries = listdir(path) if st["type"] == "dir" else [(path, st["type"])]
        except OSError as e:
            eprint("ls: " + path + ": " + e.args[1])
            rc = 1
            continue
        if len(paths) > 1:
            print(path + ":")
        for name, typ in entries:
            shown = name + ("/" if typ == "dir" else "")
            if longfmt:
                full = name if st["type"] != "dir" else (path.rstrip("/") + "/" + name)
                try:
                    s = stat(full)
                    print("{:<4} {:>8} {}".format(typ, s["size"], shown))
                except OSError:
                    print("{:<4} {:>8} {}".format(typ, "?", shown))
            else:
                print(shown)
    return rc
