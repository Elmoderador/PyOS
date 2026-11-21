# /bin/wc
def main(argv):
    data = read_all(STDIN) if len(argv) < 2 else read_file(argv[1])
    text = data.decode("utf-8", "replace")
    print("{} {} {}".format(text.count("\n"), len(text.split()), len(data)))
