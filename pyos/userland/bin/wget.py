# /bin/wget URL [-O fichero] — descarga por HTTP
def main(argv):
    include("/lib/http.py")
    args = argv[1:]
    out = None
    if "-O" in args:
        i = args.index("-O")
        out = args[i + 1]
        del args[i:i + 2]
    if not args:
        print("uso: wget http://host[:puerto]/ruta [-O fichero]")
        return 2
    url = args[0]
    t0 = uptime_ms()
    try:
        status, hdrs, body, final = http_get(url)
    except OSError as e:
        print("wget: %s" % e)
        return 1
    if out is None:
        name = final.rstrip("/").split("/")[-1]
        out = name if name and "." in name and ":" not in name else "index.html"
    if out == "-":
        write(STDOUT, body)
        return 0 if status == 200 else 1
    write_file(out, body)
    dt = max(1, uptime_ms() - t0)
    print("HTTP %d — %d bytes en %.1f s (%.1f KiB/s) -> %s"
          % (status, len(body), dt / 1000.0, len(body) / 1.024 / dt, out))
    return 0 if status == 200 else 1
