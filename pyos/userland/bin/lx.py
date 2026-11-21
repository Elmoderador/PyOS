# /bin/lx — ejecuta programas en el kernel Linux real que hay debajo de PyOS.
#   lx                    estado del subsistema
#   lx orden args...      ejecuta y muestra la salida (sin entrada)
#   lx -i orden args...   interactivo: tus líneas van a su entrada estándar
#   lx shell              shell de Linux interactiva (/bin/sh -i)
# Solo funciona si PyOS corre alojado sobre Linux con el subsistema activado.
writer = 0
handle = 0


def stop_all(sig):
    if writer:
        try:
            kill(writer, SIGKILL)
        except OSError:
            pass
    if handle:
        try:
            lx_kill(handle)
        except OSError:
            pass
    exit(130)


def feed(h):
    """Proceso hijo: líneas de la consola -> stdin del proceso Linux. Ctrl-D cierra."""
    while True:
        line = readline()
        if not line:
            lx_close(h)
            exit(0)
        if lx_write(h, line) < 0:
            exit(0)


def main(argv):
    global writer, handle
    info = lx_available()
    if len(argv) < 2:
        if not info.get("available"):
            print("lx: subsistema Linux no disponible.")
            print("    " + info.get("reason", ""))
            return 1
        print("subsistema Linux: %s, kernel %s (%s)" % (info["distro"], info["kernel"], info["arch"]))
        print("uso: lx [-i] orden args... | lx shell")
        return 0
    if not info.get("available"):
        print("lx: " + info.get("reason", "subsistema Linux no disponible"))
        return 1
    args = argv[1:]
    interactive = False
    if args[0] == "shell":
        args = ["/bin/sh", "-i"]
        interactive = True
    elif args[0] == "-i":
        args = args[1:]
        interactive = True
    if not args:
        print("lx: falta la orden")
        return 2
    try:
        handle = lx_spawn(args)
    except OSError as e:
        print("lx: %s: %s" % (args[0], strerror(e.errno) if e.errno else e))
        return 127
    signal(SIGINT, stop_all)
    if interactive:
        pid = fork()
        if pid == 0:
            feed(handle)
        writer = pid
    else:
        lx_close(handle)
    while True:
        data = lx_read(handle, 4096)
        if not data:
            break
        write(STDOUT, data)
    status = lx_wait(handle)
    if writer:
        try:
            kill(writer, SIGKILL)
        except OSError:
            pass
        waitpid(writer)
    return status
