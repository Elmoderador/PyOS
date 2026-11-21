# /bin/nc host puerto      conecta y muestra lo que llegue (lo que escribas se envía)
# /bin/nc -l puerto        espera una conexión
def main(argv):
    if len(argv) < 3:
        print("uso: nc host puerto | nc -l puerto")
        return 2
    try:
        if argv[1] == "-l":
            srv = socket("tcp")
            bind(srv, int(argv[2]))
            listen(srv, 1)
            print("nc: esperando en el puerto %s..." % argv[2])
            fd, ip, port = accept(srv)
            close(srv)
            print("nc: conexión de %s:%d" % (ip, port))
        else:
            fd = socket("tcp")
            connect(fd, argv[1], int(argv[2]))
    except OSError as e:
        print("nc: %s" % e)
        return 1
    pid = fork()
    if pid == 0:                         # hijo: teclado -> red
        while True:
            line = readline()
            if not line:
                break
            send_all(fd, line)
        exit(0)
    while True:                          # padre: red -> pantalla
        data = read(fd, 4096)
        if not data:
            break
        write(STDOUT, data)
    try:
        kill(pid, SIGKILL)
        waitpid(pid)
    except OSError:
        pass
    close(fd)
    return 0
