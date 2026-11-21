# /sbin/logd — servicio: copia las líneas nuevas del log del kernel a /var/log/kernel.log.
# El log del kernel es un anillo: se localiza la última línea ya copiada (llevan
# marca de tiempo) en lugar de contar líneas.
LOG = "/var/log/kernel.log"


def new_lines(lines, last):
    if last is None:
        return lines
    i = len(lines) - 1
    while i >= 0:
        if lines[i] == last:
            return lines[i + 1:]
        i -= 1
    return lines


def main(argv):
    last = None
    while True:
        lines = dmesg().splitlines()
        new = new_lines(lines, last)
        if new:
            write_file(LOG, "\n".join(new) + "\n", append=True)
            last = new[-1]
        sleep_ms(2000)
