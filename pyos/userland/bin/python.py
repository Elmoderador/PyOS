# /bin/python — intérprete de Python de PyOS: REPL y ejecución de scripts.
# El código se compila con el compilador del kernel y corre en la CPU virtual PVM.
VERSION = "Python 3 (PyOS PVM 2.0)"


def mostrar_error(e):
    msg = str(e)
    eprint("%s: %s" % (type(e).__name__, msg) if msg else type(e).__name__)


def ejecutar(fuente, nombre):
    fn, es_expr = pycompile(fuente, nombre)
    fn()
    return es_expr


def _sigint(sig):
    raise KeyboardInterrupt()


def repl():
    signal(SIGINT, _sigint)      # Ctrl-C -> KeyboardInterrupt dentro del programa
    print(VERSION)
    print('Escribe código Python. Bloques: termina con una línea vacía. Salir: exit() o Ctrl-D.')
    while True:
        try:
            linea = input(">>> ")
        except EOFError:
            print("")
            return 0
        except (KeyboardInterrupt, OSError):
            print("KeyboardInterrupt")
            continue
        if not linea.strip():
            continue
        fuente = linea
        if linea.rstrip().endswith(":") or linea.rstrip().endswith("\\"):
            while True:
                try:
                    mas = input("... ")
                except EOFError:
                    break
                if not mas.strip():
                    break
                fuente += "\n" + mas
        try:
            if ejecutar(fuente + "\n", "<stdin>") and _ is not None:
                print(repr(_))
        except SyntaxError as e:
            eprint("SyntaxError: " + str(e))
        except KeyboardInterrupt:
            print("KeyboardInterrupt")
        except Exception as e:
            mostrar_error(e)


def main(argv):
    args = argv[1:]
    if args and args[0] in ("--version", "-V", "-v"):
        print(VERSION)
        return 0
    if args and args[0] == "-c":
        try:
            ejecutar(" ".join(args[1:]) + "\n", "<string>")
        except Exception as e:
            mostrar_error(e)
            return 1
        return 0
    if args:
        try:
            ejecutar(read_file(args[0]).decode("utf-8"), args[0])
        except OSError as e:
            eprint("python: no se puede abrir '%s': %s" % (args[0], e.args[1] if len(e.args) > 1 else e))
            return 2
        except Exception as e:
            mostrar_error(e)
            return 1
        return 0
    return repl()


_ = None
