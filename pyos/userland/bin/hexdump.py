# /bin/hexdump
def main(argv):
    data = read_file(argv[1]) if len(argv) > 1 else read_all(STDIN)
    limit = int(argv[2]) if len(argv) > 2 else len(data)
    for off in range(0, min(len(data), limit), 16):
        row = data[off:off + 16]
        hx = " ".join("{:02x}".format(b) for b in row)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print("{:08x}  {:<48} |{}|".format(off, hx, asc))
