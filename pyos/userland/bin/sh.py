# /bin/sh — shell de PyOS: tuberías, redirecciones (<, >, >>), '&', comillas.

PATH = ["/bin", "/sbin"]
BUILTINS = ["cd", "pwd", "exit", "help", "jobs"]
jobs = []


def tokenize(line):
    toks, cur, quote, i, have = [], "", None, 0, False
    while i < len(line):
        c = line[i]
        if quote:
            if c == quote:
                quote = None
            else:
                cur += c
        elif c in "'\"":
            quote, have = c, True
        elif c == "#" and not cur and not have:
            break
        elif c in " \t":
            if cur or have:
                toks.append(cur)
            cur, have = "", False
        elif c in "|<&":
            if cur or have:
                toks.append(cur)
            toks.append(("op", c))
            cur, have = "", False
        elif c == ">":
            if cur or have:
                toks.append(cur)
            if line[i + 1:i + 2] == ">":
                toks.append(("op", ">>"))
                i += 1
            else:
                toks.append(("op", ">"))
            cur, have = "", False
        else:
            cur += c
        i += 1
    if quote:
        raise ValueError("comillas sin cerrar")
    if cur or have:
        toks.append(cur)
    return toks


def parse(toks):
    cmds, cur, bg = [], {"argv": [], "in": None, "out": None, "append": False}, False
    i = 0
    while i < len(toks):
        t = toks[i]
        if isinstance(t, tuple):
            op = t[1]
            if op == "|":
                if not cur["argv"]:
                    raise ValueError("tubería vacía")
                cmds.append(cur)
                cur = {"argv": [], "in": None, "out": None, "append": False}
            elif op == "&":
                if i != len(toks) - 1:
                    raise ValueError("'&' solo al final")
                bg = True
            else:
                if i + 1 >= len(toks) or isinstance(toks[i + 1], tuple):
                    raise ValueError("falta fichero tras " + op)
                i += 1
                if op == "<":
                    cur["in"] = toks[i]
                else:
                    cur["out"], cur["append"] = toks[i], op == ">>"
        else:
            cur["argv"].append(t)
        i += 1
    if cur["argv"]:
        cmds.append(cur)
    elif cmds:
        raise ValueError("tubería vacía")
    return cmds, bg


def find_program(name):
    if "/" in name:
        cands = [name, name + ".py"]
    else:
        cands = [d + "/" + name + ".py" for d in PATH] + [d + "/" + name for d in PATH]
    for c in cands:
        try:
            if stat(c)["type"] == "file":
                return c
        except OSError:
            pass
    return None


def builtin(argv):
    cmd = argv[0]
    if cmd == "cd":
        chdir(argv[1] if len(argv) > 1 else "/root")
    elif cmd == "pwd":
        print(getcwd())
    elif cmd == "exit":
        exit(int(argv[1]) if len(argv) > 1 else 0)
    elif cmd == "jobs":
        reap_jobs()
        for pid, name in jobs:
            print("[" + str(pid) + "] " + name)
    elif cmd == "help":
        print("builtins: " + " ".join(BUILTINS) + "      (prueba también: python)")
        print("programas: " + " ".join(sorted(n[:-3] for n, t in listdir("/bin") if n.endswith(".py"))))
        print("admin:     " + " ".join(sorted(n[:-3] for n, t in listdir("/sbin") if n.endswith(".py") and n != "init.py")))
        print("sintaxis: cmd args | cmd2 < in > out >> app &      Ctrl-C interrumpe, Ctrl-D sale")


def reap_jobs():
    while True:
        try:
            pid, status = waitpid(-1, True)
        except OSError:
            return
        if pid == 0:
            return
        for j in jobs:
            if j[0] == pid:
                jobs.remove(j)
                print("[" + str(pid) + "] terminado (" + status_text(status) + ") " + j[1])


def run(cmds, bg):
    if len(cmds) == 1 and cmds[0]["argv"][0] in BUILTINS:
        builtin(cmds[0]["argv"])
        return 0
    pids, opened, prev = [], [], None
    try:
        for idx, c in enumerate(cmds):
            path = find_program(c["argv"][0])
            if path is None:
                raise OSError(2, c["argv"][0] + ": orden no encontrada")
            fds = {0: 0, 1: 1, 2: 2}
            if prev is not None:
                fds[0] = prev
            nxt = None
            if idx < len(cmds) - 1:
                r, w = pipe()
                opened += [r, w]
                fds[1], nxt = w, r
            if c["in"]:
                fd = open(c["in"])
                opened.append(fd)
                fds[0] = fd
            if c["out"]:
                fd = open(c["out"], O_WRONLY | O_CREAT | (O_APPEND if c["append"] else O_TRUNC))
                opened.append(fd)
                fds[1] = fd
            pids.append(spawn(path, c["argv"], fds))
            prev = nxt
    finally:
        for fd in opened:
            close(fd)
    if bg:
        name = " | ".join(" ".join(c["argv"]) for c in cmds)
        jobs.append((pids[-1], name))
        print("[" + str(pids[-1]) + "]")
        return 0
    setfg(pids)
    status = 0
    try:
        for pid in pids:
            p, status = waitpid(pid)
    finally:
        setfg([])
    if status > 128:
        print(status_text(status))
    return status


def main(argv):
    script = None
    if len(argv) > 1:
        script = open(argv[1])
    src = script if script is not None else STDIN
    status = 0
    while True:
        reap_jobs()
        if script is None:
            write(STDOUT, "root@pyos:" + getcwd() + "# ")
        line = readline(src)
        if not line:
            if script is None:
                print("exit")
            return status
        try:
            toks = tokenize(line.strip())
            if not toks:
                continue
            cmds, bg = parse(toks)
            if cmds:
                status = run(cmds, bg)
        except ValueError as e:
            eprint("sh: error de sintaxis: " + str(e))
            status = 2
        except OSError as e:
            msg = e.args[1] if len(e.args) > 1 else str(e)
            eprint("sh: " + msg)
            status = 127 if e.args and e.args[0] == 2 else 1
