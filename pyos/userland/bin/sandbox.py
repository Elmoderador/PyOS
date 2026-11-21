# /bin/sandbox — intenta escapar de la PVM por vías conocidas. Todas deben fallar.
def intenta(nombre, f):
    try:
        r = f()
        print("  [ESCAPE] %-28s -> %r" % (nombre, r))
        return 1
    except Exception as e:
        print("  [bloqueado] %-25s %s" % (nombre, type(e).__name__))
        return 0


def gen():
    yield 1


def main(argv):
    print("Intentos de escape de la CPU virtual:")
    fallos = 0
    fallos += intenta("().__class__", lambda: ().__class__)
    fallos += intenta("generador.gi_frame", lambda: gen().gi_frame)
    fallos += intenta("funcion.code (interno)", lambda: main.code)
    fallos += intenta("funcion.globals (interno)", lambda: main.globals)
    fallos += intenta("syscall.pid (puerta)", lambda: syscall.pid)
    fallos += intenta("__import__('os')", lambda: __import__("os"))
    fallos += intenta("eval('1')", lambda: eval("1"))
    fallos += intenta("construir puerta syscall", lambda: type(syscall)(1))
    fallos += intenta("type(f).mro", lambda: type(main).mro)
    fallos += intenta("excepción.__traceback__", lambda: ValueError().__traceback__)
    print("resultado: %s" % ("PVM íntegra" if not fallos else "%d ESCAPES" % fallos))
    return fallos
