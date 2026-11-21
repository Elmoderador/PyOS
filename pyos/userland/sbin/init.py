# /sbin/init — PID 1. Lee el modo de arranque (mode=term|look) de /proc/cmdline,
# arranca los servicios habilitados, lanza la interfaz y apaga al terminar ésta.

def cmdline_args():
    args = {}
    try:
        for tok in read_file("/proc/cmdline").decode().split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                args[k] = v
    except OSError:
        pass
    return args


def run_and_wait(path, argv, cwd="/"):
    try:
        pid = spawn(path, argv, cwd=cwd)
    except OSError as e:
        print("init: no se pudo lanzar %s: %s" % (path, e))
        return None
    while True:
        try:
            got, status = waitpid(-1)
        except OSError:
            return None
        if got == pid:
            return status


def main(argv):
    mode = cmdline_args().get("mode", "term")
    try:
        print(read_file("/etc/motd").decode(), end="")
    except OSError:
        pass
    if exists("/sbin/svc.py"):
        run_and_wait("/sbin/svc.py", ["svc", "boot"])
    if mode == "look":
        if exists("/bin/look.py"):
            status = run_and_wait("/bin/look.py", ["look"], "/root")
            if status == 2:
                print("init: has salido de PyOS LOOK; arrancando PyOS Term.")
            elif status != 0:
                print("init: PyOS LOOK no pudo arrancar (estado %s); arrancando PyOS Term." % status)
        else:
            print("init: PyOS LOOK no está instalado en este sistema.")
            print("      Arrancando PyOS Term. Instálalo con: pkg install look")
    print("PyOS Term — 'help' lista las órdenes, 'pyos' la administración del sistema.")
    shell = spawn("/bin/sh.py", ["sh"], cwd="/root")
    while True:
        try:
            pid, status = waitpid(-1)
        except OSError:
            break
        if pid == shell:
            break
    print("init: la interfaz terminó, apagando el sistema")
    sync()
    reboot("poweroff")
    while True:
        sleep_ms(1000)
