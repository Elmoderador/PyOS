# /bin/uptime
def main(argv):
    ms = uptime_ms()
    print("up {}.{:03d} s".format(ms // 1000, ms % 1000))
