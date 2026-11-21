# /bin/edit FICHERO — editor de líneas (estilo ed) para crear programas dentro de PyOS.
AYUDA = """órdenes:
  p            mostrar el fichero con números de línea
  a            añadir líneas al final (termina con una línea que sea solo '.')
  i N          insertar antes de la línea N (termina con '.')
  d N          borrar la línea N
  r N TEXTO    reemplazar la línea N por TEXTO
  w            guardar        q  salir        wq  guardar y salir
  h            esta ayuda"""


def leer_bloque():
    nuevas = []
    while True:
        try:
            l = input("")
        except EOFError:
            break
        if l == ".":
            break
        nuevas.append(l)
    return nuevas


def main(argv):
    if len(argv) < 2:
        eprint("uso: edit FICHERO")
        return 2
    path = argv[1]
    try:
        lineas = read_file(path).decode("utf-8").split("\n")
        if lineas and lineas[-1] == "":
            lineas.pop()
    except OSError:
        lineas = []
    print("edit: %s (%d líneas). 'h' para ayuda." % (path, len(lineas)))
    sucio = False
    while True:
        try:
            orden = input("edit> ").strip()
        except EOFError:
            break
        if not orden:
            continue
        partes = orden.split(" ", 2)
        cmd = partes[0]
        try:
            if cmd == "h":
                print(AYUDA)
            elif cmd == "p":
                for n, l in enumerate(lineas, 1):
                    print("%4d  %s" % (n, l))
            elif cmd == "a":
                lineas += leer_bloque()
                sucio = True
            elif cmd == "i":
                n = int(partes[1])
                lineas[n - 1:n - 1] = leer_bloque()
                sucio = True
            elif cmd == "d":
                del lineas[int(partes[1]) - 1]
                sucio = True
            elif cmd == "r":
                lineas[int(partes[1]) - 1] = partes[2] if len(partes) > 2 else ""
                sucio = True
            elif cmd in ("w", "wq"):
                write_file(path, "\n".join(lineas) + "\n")
                print("guardado: %d líneas" % len(lineas))
                sucio = False
                if cmd == "wq":
                    return 0
            elif cmd == "q":
                if sucio:
                    print("hay cambios sin guardar (usa w, o q! para salir igualmente)")
                else:
                    return 0
            elif cmd == "q!":
                return 0
            else:
                print("orden desconocida; 'h' para ayuda")
        except (ValueError, IndexError):
            print("argumento inválido")
    return 0
