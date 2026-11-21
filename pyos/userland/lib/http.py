# /lib/http.py — cliente HTTP/1.0 mínimo. include("/lib/http.py")


def parse_url(url):
    if "://" in url:
        scheme, rest = url.split("://", 1)
    else:
        scheme, rest = "http", url
    if scheme != "http":
        raise OSError(93, "solo http:// (PyOS no tiene TLS para https)")
    host, _, path = rest.partition("/")
    path = "/" + path
    port = 80
    if ":" in host:
        host, p = host.split(":", 1)
        port = int(p)
    return host, port, path


def http_get(url, limit=4 * 1024 * 1024, progress=None, redirects=3):
    """Devuelve (estado, cabeceras dict, cuerpo bytes, url final)."""
    for _ in range(redirects + 1):
        host, port, path = parse_url(url)
        fd = socket("tcp")
        try:
            connect(fd, host, port)
            req = "GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: PyOS/2 (Python)\r\nConnection: close\r\n\r\n" % (path, host)
            send_all(fd, req)
            data = bytearray()
            while len(data) < limit:
                chunk = read(fd, 16384)
                if not chunk:
                    break
                data += chunk
                if progress is not None:
                    progress(len(data))
        finally:
            close(fd)
        head, _, body = bytes(data).partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            status = int(lines[0].split()[1])
        except (IndexError, ValueError):
            raise OSError(71, "respuesta HTTP inválida")
        hdrs = {}
        for l in lines[1:]:
            if ":" in l:
                k, v = l.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        if status in (301, 302, 303, 307, 308) and "location" in hdrs:
            loc = hdrs["location"]
            if loc.startswith("/"):
                loc = "http://%s%s%s" % (host, ":%d" % port if port != 80 else "", loc)
            url = loc
            continue
        return status, hdrs, body, url
    raise OSError(31, "demasiadas redirecciones")
