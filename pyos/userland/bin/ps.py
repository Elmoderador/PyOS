# /bin/ps
def field(text, key):
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return "?"


def main(argv):
    print("{:>4} {:>4} {:<8} {:>6} {:>8} {:<6} {}".format("PID", "PPID", "STATE", "TICKS", "RSS", "WCHAN", "CMD"))
    for name, typ in listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            st = read_file("/proc/" + name + "/status").decode()
            cmd = read_file("/proc/" + name + "/cmdline").decode().strip()
        except OSError:
            continue
        print("{:>4} {:>4} {:<8} {:>6} {:>8} {:<6} {}".format(
            name, field(st, "PPid"), field(st, "State"), field(st, "CpuTicks"),
            field(st, "VmRSS"), field(st, "WChan"), cmd))
