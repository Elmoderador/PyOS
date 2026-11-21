# /bin/ping [-c N] host — eco ICMP
def main(argv):
    count = 4
    args = argv[1:]
    if len(args) >= 2 and args[0] == "-c":
        count = int(args[1])
        args = args[2:]
    if not args:
        print("uso: ping [-c N] host")
        return 2
    host = args[0]
    try:
        ips = resolve(host)
    except OSError as e:
        print("ping: %s: %s" % (host, e))
        return 2
    if not ips:
        print("ping: %s: nombre desconocido" % host)
        return 2
    ip = ips[0]
    ident = getpid() & 0xFFFF
    print("PING %s (%s): 56 bytes de datos" % (host, ip))
    ok = 0
    rtts = []
    for seq in range(1, count + 1):
        t0 = uptime_ms()
        try:
            rtt = ping(ip, ident, seq, 2000)
        except OSError as e:
            print("ping: %s" % e)
            return 2
        if rtt is None:
            print("sin respuesta de %s: seq=%d" % (ip, seq))
        else:
            ok += 1
            rtts.append(rtt)
            print("64 bytes de %s: seq=%d tiempo=%.1f ms" % (ip, seq, rtt))
        if seq < count:
            sleep_ms(max(0, 1000 - (uptime_ms() - t0)))
    print("--- %s ---" % host)
    print("%d enviados, %d recibidos, %d%% perdidos" % (count, ok, 100 * (count - ok) // count))
    if rtts:
        print("rtt mín/media/máx = %.1f/%.1f/%.1f ms" % (min(rtts), sum(rtts) / len(rtts), max(rtts)))
    return 0 if ok else 1
