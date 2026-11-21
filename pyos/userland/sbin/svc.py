# /sbin/svc — gestor de servicios de PyOS.
#   svc list | status [n] | start n | stop n | restart n | enable n | disable n | boot
# Definiciones en /etc/svc/<n>.svc (name/exec/args/description), habilitados en
# /etc/svc/enabled, PID en /var/run/<n>.pid, salida del servicio en /var/log/<n>.log.
SVCDIR = "/etc/svc"
ENABLED = SVCDIR + "/enabled"
RUN = "/var/run"


def parse(name):
    try:
        text = read_file(SVCDIR + "/" + name + ".svc").decode()
    except OSError:
        return None
    d = {"name": name, "args": "", "description": ""}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    if "exec" not in d:
        return None
    return d


def services():
    return sorted(n[:-4] for n, t in listdir(SVCDIR) if n.endswith(".svc"))


def enabled():
    try:
        return [l.strip() for l in read_file(ENABLED).decode().splitlines() if l.strip()]
    except OSError:
        return []


def set_enabled(names):
    write_file(ENABLED, "".join(n + "\n" for n in names))


def pid_of(name):
    """PID si el servicio sigue vivo (comprueba /proc/<pid>/cmdline, no solo el pidfile)."""
    try:
        pid = int(read_file(RUN + "/" + name + ".pid").decode().strip())
    except (OSError, ValueError):
        return None
    try:
        cmd = read_file("/proc/%d/cmdline" % pid).decode()
    except OSError:
        return None
    parts = cmd.split()
    return pid if parts and parts[0] == name else None


def start(name):
    d = parse(name)
    if d is None:
        print("svc: servicio desconocido o mal definido: " + name)
        return 1
    pid = pid_of(name)
    if pid is not None:
        print("svc: %s ya está en marcha (pid %d)" % (name, pid))
        return 0
    log = open("/var/log/" + name + ".log", O_WRONLY | O_CREAT | O_APPEND)
    try:
        pid = spawn(d["exec"], [name] + d["args"].split(), {1: log, 2: log}, "/")
    except OSError as e:
        print("svc: no se pudo arrancar %s: %s" % (name, e))
        return 1
    finally:
        close(log)
    write_file(RUN + "/" + name + ".pid", str(pid) + "\n")
    print("svc: %s arrancado (pid %d)" % (name, pid))
    return 0


def stop(name):
    pid = pid_of(name)
    if pid is None:
        print("svc: %s no está en marcha" % name)
        return 1
    kill(pid, SIGTERM)
    try:
        unlink(RUN + "/" + name + ".pid")
    except OSError:
        pass
    print("svc: %s detenido (pid %d)" % (name, pid))
    return 0


def status(names):
    en = enabled()
    print("%-10s %-10s %-8s %s" % ("SERVICIO", "ESTADO", "ARRANQUE", "DESCRIPCIÓN"))
    for n in names:
        d = parse(n)
        pid = pid_of(n)
        st = ("activo:%d" % pid) if pid else "parado"
        print("%-10s %-10s %-8s %s" % (n, st, "sí" if n in en else "no",
                                       d["description"] if d else "(definición inválida)"))
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print("uso: svc list | status [srv] | start|stop|restart|enable|disable srv | boot")
        return 0
    cmd = argv[1]
    arg = argv[2] if len(argv) > 2 else None
    if cmd in ("list", "status"):
        return status([arg] if arg else services())
    if cmd == "boot":
        for n in enabled():
            start(n)
        return 0
    if arg is None:
        print("svc: falta el nombre del servicio")
        return 2
    if cmd == "start":
        return start(arg)
    if cmd == "stop":
        return stop(arg)
    if cmd == "restart":
        stop(arg)
        sleep_ms(50)
        return start(arg)
    if cmd in ("enable", "disable"):
        if parse(arg) is None:
            print("svc: servicio desconocido: " + arg)
            return 1
        en = [n for n in enabled() if n != arg]
        if cmd == "enable":
            en.append(arg)
        set_enabled(en)
        print("svc: %s %s en el arranque" % (arg, "habilitado" if cmd == "enable" else "deshabilitado"))
        return 0
    print("svc: orden desconocida: " + cmd)
    return 2
