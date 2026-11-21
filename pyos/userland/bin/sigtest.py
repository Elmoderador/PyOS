# /bin/sigtest — manejadores de señales de usuario ejecutados por la PVM.
recibidas = []


def manejador(sig):
    recibidas.append(sig)
    print("  manejador: recibida señal %d" % sig)


def main(argv):
    signal(SIGTERM, manejador)
    signal(SIGINT, manejador)
    yo = getpid()
    kill(yo, SIGTERM)
    print("tras kill(SIGTERM) a mí mismo; recibidas=%r" % recibidas)
    signal(SIGINT, "ignore")
    kill(yo, SIGINT)
    print("SIGINT ignorada; recibidas=%r" % recibidas)
    pid = fork()
    if pid == 0:
        signal(SIGTERM, manejador)
        while not recibidas:
            sleep_ms(20)
        print("  hijo: me llegó SIGTERM, salgo limpiamente")
        exit(0)
    sleep_ms(100)
    kill(pid, SIGTERM)
    p, st = waitpid(pid)
    print("hijo %d terminó con %d" % (p, st))
    return 0
