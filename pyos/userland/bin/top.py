# /bin/top — una instantánea de procesos con instrucciones PVM ejecutadas.
def field(text, key):
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return "?"


def main(argv):
    print("{:>4} {:<8} {:>12} {:>8} {:>7}  {}".format("PID", "ESTADO", "INSTRUCC.", "SYSCALLS", "RSS", "CMD"))
    for name, typ in listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            st = read_file("/proc/" + name + "/status").decode()
        except OSError:
            continue
        print("{:>4} {:<8} {:>12} {:>8} {:>7}  {}".format(
            name, field(st, "State"), field(st, "Instructions"), field(st, "Syscalls"),
            field(st, "VmRSS"), field(st, "Name")))
    print(read_file("/proc/stat").decode(), end="")
