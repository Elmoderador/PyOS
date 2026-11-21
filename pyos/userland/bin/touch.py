# /bin/touch
def main(argv):
    for p in argv[1:]:
        close(open(p, O_WRONLY | O_CREAT))
