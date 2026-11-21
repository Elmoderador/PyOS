# /bin/df
def main(argv):
    s = statfs()
    bs = s["block_size"] // 1024
    used = s["blocks"] - s["free_blocks"]
    print("Filesystem   1K-blocks     Used    Avail  Inodes(free)  Mounted on")
    print("pyfs        {:>10} {:>8} {:>8}  {:>5}({:>5})  /".format(
        s["blocks"] * bs, used * bs, s["free_blocks"] * bs, s["inodes"], s["free_inodes"]))
