# /bin/stat
def main(argv):
    for p in argv[1:]:
        s = stat(p)
        print(p + ": " + " ".join(k + "=" + str(s[k]) for k in sorted(s)))
