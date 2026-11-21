# /bin/write
# write FICHERO TEXTO... : escribe texto en un fichero (sin necesitar redirección)
def main(argv):
    write_file(argv[1], " ".join(argv[2:]) + "\n")
