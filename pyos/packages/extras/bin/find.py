# find [dir] [-name PATRÓN] [-type f|d] — PATRÓN admite * y ?
def match(pat, s):
    if not pat:
        return not s
    if pat[0] == "*":
        return match(pat[1:], s) or (bool(s) and match(pat, s[1:]))
    return bool(s) and (pat[0] == "?" or pat[0] == s[0]) and match(pat[1:], s[1:])


def walk(path, name, typ):
    try:
        entries = sorted(listdir(path))
    except OSError:
        return
    for n, t in entries:
        full = path.rstrip("/") + "/" + n
        kind = "d" if t == "dir" else "f"
        if (name is None or match(name, n)) and (typ is None or typ == kind):
            print(full)
        if t == "dir":
            walk(full, name, typ)


def main(argv):
    root = "."
    name = typ = None
    i = 1
    while i < len(argv):
        if argv[i] == "-name" and i + 1 < len(argv):
            name = argv[i + 1]
            i += 2
        elif argv[i] == "-type" and i + 1 < len(argv):
            typ = argv[i + 1]
            i += 2
        else:
            root = argv[i]
            i += 1
    walk(root, name, typ)
