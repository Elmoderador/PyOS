# adivina — adivina el número (1..100); usa /dev/random
def main(argv):
    fd = open("/dev/random")
    r = read(fd, 2)
    close(fd)
    secret = (r[0] * 256 + r[1]) % 100 + 1
    print("He pensado un número del 1 al 100.")
    for intento in range(1, 8):
        s = input("intento %d/7> " % intento)
        if not s:
            return 1
        try:
            n = int(s)
        except ValueError:
            print("eso no es un número")
            continue
        if n == secret:
            print("¡Correcto en %d intentos!" % intento)
            return 0
        print("más alto" if n < secret else "más bajo")
    print("Se acabaron los intentos: era %d" % secret)
    return 1
