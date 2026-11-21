# /bin/forktest — fork() real: el hijo hereda una COPIA de toda la memoria del padre.
def main(argv):
    datos = {"lista": [1, 2, 3], "texto": "original"}
    contador = 0
    def gen():
        n = 0
        while True:
            n += 1
            yield n
    g = gen()
    next(g); next(g)                     # el generador va por 2
    pid = fork()
    if pid == 0:
        datos["lista"].append("hijo")
        datos["texto"] = "modificado por el hijo"
        print("[hijo  pid=%d] datos=%r siguiente del generador=%d" % (getpid(), datos, next(g)))
        exit(7)
    datos["lista"].append("padre")
    print("[padre pid=%d] hijo=%d datos=%r siguiente del generador=%d" % (getpid(), pid, datos, next(g)))
    p, status = waitpid(pid)
    print("[padre] el hijo %d terminó con estado %d" % (p, status))
    pid2 = fork()
    if pid2 == 0:
        exec("/bin/echo.py", ["echo", "soy el hijo tras exec()"])
    waitpid(pid2)
    return 0
