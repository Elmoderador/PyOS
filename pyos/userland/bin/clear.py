# /bin/clear — limpia la pantalla.
def main(argv):
    write(STDOUT, "\x1b[2J")
