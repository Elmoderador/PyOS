# /bin/spin
# spin [segundos]: bucle de CPU puro (sin syscalls). Sirve para comprobar la apropiación.
def main(argv):
    secs = float(argv[1]) if len(argv) > 1 else 0
    start = uptime_ms()
    n = 0
    while True:
        n += 1
        if secs and n % 2000 == 0 and uptime_ms() - start >= secs * 1000:
            break
    print("spin: " + str(n) + " iteraciones")
