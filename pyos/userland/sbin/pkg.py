# /sbin/pkg — gestor de paquetes de PyOS (repositorio local, sin red).
#   pkg list | avail | info P | files P | install P|fichero.pkg | remove P | verify P
# Repositorio: /var/pkg/repo/*.pkg (formato PYOSPKG 1). Base de datos: /var/pkg/db/<P>.
REPO = "/var/pkg/repo"
DB = "/var/pkg/db"
PROTECTED = ("/sbin/init.py", "/sbin/pkg.py", "/lib/libpy.py", "/bin/sh.py")


class BadPackage(Exception):
    pass


def parse_pkg(data):
    """bytes -> (meta, [(ruta, datos)]). Valida cabecera, tamaños y rutas."""
    if not data.startswith(b"PYOSPKG 1\n"):
        raise BadPackage("cabecera PYOSPKG 1 no encontrada")
    pos = len(b"PYOSPKG 1\n")
    meta = {}
    files = []
    while True:
        nl = data.find(b"\n", pos)
        if nl < 0:
            raise BadPackage("paquete truncado")
        line = data[pos:nl].decode()
        pos = nl + 1
        if line == "end":
            break
        if line.startswith("file "):
            parts = line.split(" ")
            if len(parts) != 3:
                raise BadPackage("entrada de fichero inválida: " + line)
            path = parts[1]
            size = int(parts[2])
            if not path.startswith("/") or ".." in path.split("/") or path in PROTECTED:
                raise BadPackage("ruta no permitida: " + path)
            if pos + size + 1 > len(data) or data[pos + size:pos + size + 1] != b"\n":
                raise BadPackage("tamaño incorrecto en " + path)
            files.append((path, data[pos:pos + size]))
            pos += size + 1
        elif ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
        else:
            raise BadPackage("línea inesperada: " + line)
    for key in ("name", "version"):
        if not meta.get(key):
            raise BadPackage("falta el campo " + key)
    return meta, files


def repo_index():
    idx = {}
    try:
        entries = listdir(REPO)
    except OSError:
        return idx
    for n, t in entries:
        if n.endswith(".pkg"):
            try:
                meta, files = parse_pkg(read_file(REPO + "/" + n))
            except (BadPackage, OSError, ValueError) as e:
                eprint("pkg: %s dañado en el repositorio: %s" % (n, e))
                continue
            idx[meta["name"]] = (REPO + "/" + n, meta)
    return idx


def installed():
    db = {}
    try:
        entries = listdir(DB)
    except OSError:
        return db
    for n, t in entries:
        lines = read_file(DB + "/" + n).decode().splitlines()
        meta = {}
        files = []
        for l in lines:
            if l.startswith("/"):
                files.append(l)
            elif ":" in l:
                k, v = l.split(":", 1)
                meta[k.strip()] = v.strip()
        db[n] = (meta, files)
    return db


def ensure_dirs(path):
    parts = [p for p in path.split("/") if p][:-1]
    cur = ""
    for p in parts:
        cur += "/" + p
        if not exists(cur):
            mkdir(cur)


def owners(db):
    o = {}
    for name in db:
        for f in db[name][1]:
            o[f] = name
    return o


def install(target, db, idx, stack=None):
    stack = stack or []
    if target.endswith(".pkg") and "/" in target:
        data = read_file(target)
    elif target in idx:
        data = read_file(idx[target][0])
    else:
        print("pkg: '%s' no está en el repositorio (pkg avail)" % target)
        return 1
    meta, files = parse_pkg(data)
    name = meta["name"]
    if name in db and db[name][0].get("version") == meta["version"]:
        print("pkg: %s %s ya está instalado" % (name, meta["version"]))
        return 0
    for dep in [d for d in meta.get("depends", "").replace(",", " ").split() if d]:
        if dep in stack:
            print("pkg: dependencia circular: %s" % " -> ".join(stack + [dep]))
            return 1
        if dep not in db:
            print("pkg: instalando dependencia %s" % dep)
            if install(dep, db, idx, stack + [name]) != 0:
                return 1
    own = owners(db)
    for path, blob in files:
        if path in own and own[path] != name:
            print("pkg: conflicto: %s pertenece a %s" % (path, own[path]))
            return 1
    if name in db:                                  # actualización: quita lo que ya no trae
        new = set(p for p, b in files)
        for f in db[name][1]:
            if f not in new and exists(f):
                unlink(f)
    for path, blob in files:
        ensure_dirs(path)
        write_file(path, blob)
    rec = "".join("%s: %s\n" % (k, meta.get(k, "")) for k in ("name", "version", "description", "depends"))
    rec += "".join(p + "\n" for p, b in files)
    write_file(DB + "/" + name, rec)
    db[name] = (meta, [p for p, b in files])
    sync()
    print("pkg: instalado %s %s (%d ficheros)" % (name, meta["version"], len(files)))
    return 0


def remove(name, db):
    if name not in db:
        print("pkg: %s no está instalado" % name)
        return 1
    for other in db:
        deps = db[other][0].get("depends", "").replace(",", " ").split()
        if other != name and name in deps:
            print("pkg: %s lo necesita %s; desinstala ese primero" % (name, other))
            return 1
    for f in db[name][1]:
        try:
            unlink(f)
        except OSError:
            pass
    unlink(DB + "/" + name)
    sync()
    print("pkg: desinstalado %s" % name)
    return 0


def verify(name, db, idx):
    if name not in db:
        print("pkg: %s no está instalado" % name)
        return 1
    meta = db[name][0]
    if name not in idx or idx[name][1]["version"] != meta.get("version"):
        print("pkg: no hay copia de %s %s en el repositorio para comparar" % (name, meta.get("version")))
        return 1
    m, files = parse_pkg(read_file(idx[name][0]))
    bad = 0
    for path, blob in files:
        try:
            ok = read_file(path) == blob
        except OSError:
            ok = False
        if not ok:
            print("  MODIFICADO/AUSENTE " + path)
            bad += 1
    print("pkg: %s: %d ficheros, %d con diferencias" % (name, len(files), bad))
    return 1 if bad else 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print("uso: pkg list | avail | info P | files P | install P|ruta.pkg | remove P | verify P")
        print("     (repositorio local en %s; PyOS no tiene red)" % REPO)
        return 0
    cmd = argv[1]
    arg = argv[2] if len(argv) > 2 else None
    db = installed()
    try:
        if cmd == "list":
            if not db:
                print("(ningún paquete instalado)")
            for n in sorted(db):
                print("%-12s %-8s %s" % (n, db[n][0].get("version", "?"), db[n][0].get("description", "")))
            return 0
        idx = repo_index()
        if cmd == "avail":
            for n in sorted(idx):
                m = idx[n][1]
                print("%-12s %-8s %-3s %s" % (n, m["version"], "[i]" if n in db else "", m.get("description", "")))
            return 0
        if arg is None:
            print("pkg: falta el paquete")
            return 2
        if cmd == "info":
            m = idx[arg][1] if arg in idx else (db[arg][0] if arg in db else None)
            if m is None:
                print("pkg: paquete desconocido: " + arg)
                return 1
            for k in ("name", "version", "description", "depends"):
                print("%-12s %s" % (k + ":", m.get(k, "")))
            print("%-12s %s" % ("instalado:", db[arg][0].get("version") if arg in db else "no"))
            return 0
        if cmd == "files":
            if arg not in db:
                print("pkg: %s no está instalado" % arg)
                return 1
            for f in db[arg][1]:
                print(f)
            return 0
        if cmd == "install":
            return install(arg, db, idx)
        if cmd == "remove":
            return remove(arg, db)
        if cmd == "verify":
            return verify(arg, db, idx)
    except BadPackage as e:
        print("pkg: paquete inválido: %s" % e)
        return 1
    print("pkg: orden desconocida: " + cmd)
    return 2
