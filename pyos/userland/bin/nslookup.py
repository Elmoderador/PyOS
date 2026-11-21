# /bin/nslookup nombre — resolución DNS
def main(argv):
    if len(argv) < 2:
        print("uso: nslookup nombre")
        return 2
    i = net_info()
    if i.get("available"):
        print("Servidor: %s" % i["dns"])
    try:
        ips = resolve(argv[1])
    except OSError as e:
        print("nslookup: %s" % e)
        return 1
    if not ips:
        print("** %s: no encontrado" % argv[1])
        return 1
    print("Nombre: %s" % argv[1])
    for ip in ips:
        print("Dirección: %s" % ip)
    return 0
