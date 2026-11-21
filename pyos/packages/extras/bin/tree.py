# tree [dir] — árbol de directorios
def walk(path, prefix, counts):
    try:
        entries = sorted(listdir(path))
    except OSError as e:
        print(prefix + "[error: %s]" % e)
        return
    for i, (name, typ) in enumerate(entries):
        last = i == len(entries) - 1
        print(prefix + ("└── " if last else "├── ") + name + ("/" if typ == "dir" else ""))
        if typ == "dir":
            counts[0] += 1
            walk((path.rstrip("/") + "/" + name), prefix + ("    " if last else "│   "), counts)
        else:
            counts[1] += 1


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    print(root)
    counts = [0, 0]
    walk(root, "", counts)
    print("\n%d directorios, %d ficheros" % (counts[0], counts[1]))
