# /bin/pyos-info
def main(argv):
    print(read_file("/proc/version").decode(), end="")
    print("cmdline: " + read_file("/proc/cmdline").decode(), end="")
    print(read_file("/proc/stat").decode(), end="")
    print(read_file("/proc/interrupts").decode(), end="")
    print(read_file("/proc/devices").decode(), end="")
    print(read_file("/proc/mounts").decode(), end="")
