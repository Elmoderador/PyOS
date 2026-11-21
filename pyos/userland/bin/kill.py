# /bin/kill [-SEÑAL] pid|nombre ... — con un nombre, señala a todos los procesos con ese argv[0]
def pids_named(name):
    out = []
    for n, t in listdir("/proc"):
        if n.isdigit() and int(n) not in (1, getpid()):
            try:
                cmd = read_file("/proc/" + n + "/cmdline").decode().split()
            except OSError:
                continue
            if cmd and cmd[0] == name:
                out.append(int(n))
    return out


def main(argv):
    sig = SIGTERM
    args = argv[1:]
    if args and args[0].startswith("-"):
        sig = int(args[0][1:])
        args = args[1:]
    rc = 0
    for a in args:
        targets = [int(a)] if a.isdigit() else pids_named(a)
        if not targets:
            eprint("kill: " + a + ": ningún proceso")
            rc = 1
        for pid in targets:
            try:
                kill(pid, sig)
            except OSError as e:
                eprint("kill: " + str(pid) + ": " + str(e))
                rc = 1
    return rc
