# /bin/free
def main(argv):
    print(read_file("/proc/meminfo").decode(), end="")
