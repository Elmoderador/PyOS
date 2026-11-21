# /lib/look/fetch.py URL — ayudante del Navegador de LOOK: descarga por HTTP en un proceso
# aparte para que el escritorio no se congele. Protocolo por la salida estándar:
#   P <bytes>\n            progreso (opcional, repetido)
#   OK <estado> <url>\t<content-type>\n<cuerpo>
#   ERR <mensaje>\n
include("/lib/http.py")

LIMIT = 2 * 1024 * 1024


def main(argv):
    if len(argv) < 2:
        write(1, b"ERR falta la URL\n")
        return 2
    last = [0]

    def progress(n):
        if n - last[0] >= 8192:
            last[0] = n
            write(1, ("P %d\n" % n).encode())

    try:
        code, hdrs, body, final = http_get(argv[1], limit=LIMIT, progress=progress)
    except OSError as e:
        write(1, ("ERR %s\n" % e).encode("utf-8", "replace"))
        return 1
    ctype = hdrs.get("content-type", "text/html").replace("\t", " ").replace("\n", " ")
    write(1, ("OK %d %s\t%s\n" % (code, final, ctype)).encode("utf-8", "replace"))
    i = 0
    while i < len(body):
        i += write(1, body[i:i + 16384])
    return 0
