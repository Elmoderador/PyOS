# /sbin/httpd [puerto] — servidor web: sirve /var/www y genera /estado con datos del sistema
ROOT = "/var/www"
TYPES = {"html": "text/html; charset=utf-8", "txt": "text/plain; charset=utf-8",
         "css": "text/css", "js": "application/javascript", "png": "image/png", "py": "text/plain"}


def status_page():
    u = uname()
    rows = []
    for name, t in listdir("/proc"):
        if name.isdigit():
            try:
                rows.append("<tr><td>%s</td><td>%s</td></tr>" % (
                    name, read_file("/proc/%s/cmdline" % name).decode().strip()))
            except OSError:
                pass
    return ("<html><head><title>PyOS</title></head><body style='font-family:monospace'>"
            "<h1>%s %s</h1><p>Encendido: %d s</p><pre>%s</pre><h2>Procesos</h2>"
            "<table border=1>%s</table></body></html>" % (
                u[0], u[2], uptime_ms() // 1000, read_file("/proc/meminfo").decode(), "".join(rows))).encode()


def handle(fd, ip):
    req = bytearray()
    while b"\r\n\r\n" not in req and len(req) < 8192:
        d = read(fd, 4096)
        if not d:
            break
        req += d
    line = bytes(req).split(b"\r\n", 1)[0].decode("latin-1", "replace").split()
    path = line[1] if len(line) > 1 else "/"
    code, ctype = 200, "text/html; charset=utf-8"
    if path == "/estado":
        body = status_page()
    else:
        p = ROOT + ("/index.html" if path == "/" else path.split("?")[0])
        if ".." in p.split("/"):
            code, body = 403, b"prohibido"
        else:
            try:
                body = read_file(p)
                ctype = TYPES.get(p.rsplit(".", 1)[-1], "application/octet-stream")
            except OSError:
                code, body = 404, b"<h1>404</h1><p>no existe: " + path.encode() + b"</p>"
    hdr = "HTTP/1.0 %d %s\r\nServer: PyOS-httpd\r\nContent-Type: %s\r\nContent-Length: %d\r\n\r\n" % (
        code, {200: "OK", 403: "Forbidden", 404: "Not Found"}[code], ctype, len(body))
    send_all(fd, hdr.encode() + body)
    print("httpd: %s %s %d" % (ip, path, code))


def main(argv):
    port = int(argv[1]) if len(argv) > 1 else 80
    srv = socket("tcp")
    bind(srv, port)
    listen(srv, 8)
    print("httpd: escuchando en el puerto %d" % port)
    while True:
        fd, ip, rport = accept(srv)
        try:
            handle(fd, ip)
        except OSError as e:
            print("httpd: %s" % e)
        close(fd)
