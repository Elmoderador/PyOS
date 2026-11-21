# /bin/sleep
def main(argv):
    sleep_ms(int(float(argv[1]) * 1000) if len(argv) > 1 else 1000)
