# /bin/halt
def main(argv):
    sync()
    reboot("poweroff")
