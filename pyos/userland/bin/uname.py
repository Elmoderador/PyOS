# /bin/uname
def main(argv):
    u = uname()
    print(" ".join(u) if "-a" in argv else u[0])
