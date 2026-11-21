# /bin/head
def main(argv):
    n = 10
    args = argv[1:]
    if args and args[0].startswith("-"):
        n = int(args[0][1:])
        args = args[1:]
    fd = open(args[0]) if args else STDIN
    for i in range(n):
        line = readline(fd)
        if not line:
            break
        print(line, end="")
