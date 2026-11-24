"""Analizadores estrictos de los formatos firmados de UC (SPEC_UC.md §5.1 y §5.5):
`UCMANIFEST 1`, `UCSIG 1` y `UCKEYREC 1`, y la verificación de un manifiesto con un anillo de
claves que da quien llama (este módulo no contiene ni decide claves: D1, D15).

Todo lo que no cumple la gramática se rechaza con ManifestError(motivo). Los límites se
comprueban antes de analizar.
"""
import re

from . import ed25519

MAX_BYTES = 16 * 1024
MAX_PKG_BYTES = 64 * 1024    # manifiestos UCPKG (hasta 512 ficheros)
MAX_LINE = 512
MAX_COMPONENTS = 32
KNOWN_COMPONENTS = ("kernel", "system", "bootloader")
CHANNELS = ("stable", "beta", "sandbox")
CHANGES = ("U", "P", "S", "none")
_RANK = {"none": 0, "S": 1, "P": 2, "U": 3}

_VER3 = re.compile(r"\A(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\Z")
_VER4 = re.compile(r"\A(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})"
                   r"\.(0|[1-9][0-9]{0,4})\Z")
_DATE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_HEX128 = re.compile(r"\A[0-9a-f]{128}\Z")
_ID = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,63}\Z")
_ASSET = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_INT = re.compile(r"\A(0|[1-9][0-9]{0,11})\Z")


class ManifestError(ValueError):
    pass


def _lines(data, magic, maxb=MAX_BYTES):
    if type(data) is not bytes:
        raise ManifestError("se esperaban bytes")
    if len(data) > maxb:
        raise ManifestError("demasiado grande (%d bytes; máximo %d)" % (len(data), maxb))
    for b in data:
        if b != 10 and not 0x20 <= b <= 0x7E:
            raise ManifestError("carácter no permitido (byte %d)" % b)
    if not data.endswith(b"\nend\n") and data != magic.encode() + b"\nend\n":
        raise ManifestError("debe terminar en 'end' y no tener nada detrás")
    lines = data.decode("ascii").split("\n")[:-1]           # el último '\n' cierra 'end'
    for n, line in enumerate(lines, 1):
        if len(line) > MAX_LINE:
            raise ManifestError("línea %d demasiado larga" % n)
    if lines[0] != magic:
        raise ManifestError("la primera línea debe ser '%s'" % magic)
    if lines.count("end") != 1:
        raise ManifestError("'end' debe aparecer una sola vez, al final")
    return lines[1:-1]


def _fields(lines, order, optional=(), repeat=()):
    """Comprueba orden fijo, campos obligatorios, sin repetidos ni desconocidos."""
    out, seen = {}, []
    pos = 0
    for n, line in enumerate(lines, 2):
        key, sep, value = line.partition(": ")
        if not sep or not value or value != value.strip():
            raise ManifestError("línea %d: se esperaba 'clave: valor'" % n)
        if key not in order:
            raise ManifestError("línea %d: campo desconocido '%s'" % (n, key))
        idx = order.index(key)
        if idx < pos or (key in seen and key not in repeat):
            raise ManifestError("línea %d: '%s' repetido o fuera de orden" % (n, key))
        pos = idx
        if key in repeat:
            out.setdefault(key, []).append(value)
        else:
            out[key] = value
        seen.append(key)
    for key in order:
        if key not in out and key not in optional:
            raise ManifestError("falta el campo '%s'" % key)
    return out


def _attrs(text, order, optional, n):
    out, pos = {}, 0
    for item in text.split(" "):
        k, sep, v = item.partition("=")
        if not sep or not v or k not in order:
            raise ManifestError("componente %d: atributo no válido '%s'" % (n, item))
        idx = order.index(k)
        if idx < pos or k in out:
            raise ManifestError("componente %d: '%s' repetido o fuera de orden" % (n, k))
        pos = idx
        out[k] = v
    for k in order:
        if k not in out and k not in optional:
            raise ManifestError("componente %d: falta '%s'" % (n, k))
    return out


def version_tuple(text):
    return tuple(int(x) for x in text.split("."))


def parse_manifest(data):
    order = ("version", "channel", "type", "released", "expires", "min_from", "key_id", "set",
             "boot_abi", "uc", "component", "changelog")
    f = _fields(_lines(data, "UCMANIFEST 1"), order, optional=("uc",), repeat=("component",))
    channel = f["channel"]
    if channel not in CHANNELS:
        raise ManifestError("canal desconocido '%s'" % channel)
    ver_re = _VER4 if channel == "sandbox" else _VER3          # UC-1
    for k in ("version", "min_from") + (("uc",) if "uc" in f else ()):
        if not ver_re.match(f[k]):
            raise ManifestError("'%s' no es una versión válida para el canal %s" % (k, channel))
    if f["type"] not in CHANGES[:3]:
        raise ManifestError("type debe ser U, P o S")
    for k in ("released", "expires"):
        if not _DATE.match(f[k]):
            raise ManifestError("'%s' no es una fecha AAAA-MM-DDThh:mm:ssZ" % k)
    if f["expires"] <= f["released"]:
        raise ManifestError("expires debe ser posterior a released")
    if not _ID.match(f["key_id"]):
        raise ManifestError("key_id no válido")
    if not _INT.match(f["boot_abi"]):
        raise ManifestError("boot_abi no válido")
    comps = f["component"]
    if len(comps) > MAX_COMPONENTS:
        raise ManifestError("demasiados componentes")
    components = {}
    for n, line in enumerate(comps, 1):
        parts = line.split(" ", 2)
        if len(parts) != 3:
            raise ManifestError("componente %d mal formado" % n)
        name, cver, rest = parts
        if name not in KNOWN_COMPONENTS:
            raise ManifestError("componente desconocido '%s'" % name)
        if name in components:
            raise ManifestError("componente '%s' repetido" % name)
        if not ver_re.match(cver):
            raise ManifestError("versión no válida del componente '%s'" % name)
        a = _attrs(rest, ("change", "rollback", "size", "sha256", "verity", "parts", "asset"),
                   ("verity", "parts"), n)
        if a["change"] not in CHANGES:
            raise ManifestError("change no válido en '%s'" % name)
        for k in ("rollback", "size") + (("parts",) if "parts" in a else ()):
            if not _INT.match(a[k]):
                raise ManifestError("'%s' no es un entero válido en '%s'" % (k, name))
        if ("verity" in a) != (name == "system"):
            raise ManifestError("verity es obligatorio en 'system' y no se admite en '%s'" % name)
        for k in ("sha256", "verity"):
            if k in a and not _HEX64.match(a[k]):
                raise ManifestError("'%s' de '%s' no son 64 hex en minúscula" % (k, name))
        if not _ASSET.match(a["asset"]):
            raise ManifestError("nombre de asset no válido en '%s'" % name)
        parts_n = int(a.get("parts", "1"))
        if not 1 <= parts_n <= 64:
            raise ManifestError("parts fuera de rango en '%s'" % name)
        components[name] = {"version": cver, "change": a["change"], "rollback": int(a["rollback"]),
                            "size": int(a["size"]), "sha256": a["sha256"],
                            "verity": a.get("verity"), "parts": parts_n, "asset": a["asset"]}
    top = max(_RANK[c["change"]] for c in components.values())
    if _RANK[f["type"]] != max(top, 1) or top == 0:            # UC-7
        raise ManifestError("type debe ser el máximo de los change de los componentes")
    boot_set = f["set"].split(" ")
    if len(set(boot_set)) != len(boot_set) or any(c not in components for c in boot_set):
        raise ManifestError("set debe listar componentes del manifiesto, sin repetir")
    ch = f["changelog"].split(" ")
    if len(ch) != 2 or not ch[0].startswith("sha256=") or not ch[1].startswith("asset=") \
            or not _HEX64.match(ch[0][7:]) or not _ASSET.match(ch[1][6:]):
        raise ManifestError("changelog debe ser 'sha256=<hex> asset=<nombre>'")
    return {"version": f["version"], "channel": channel, "type": f["type"],
            "released": f["released"], "expires": f["expires"], "min_from": f["min_from"],
            "key_id": f["key_id"], "set": boot_set, "boot_abi": int(f["boot_abi"]),
            "uc": f.get("uc"), "components": components,
            "order": [line.split(" ", 1)[0] for line in comps],   # orden de las líneas
            "changelog": {"sha256": ch[0][7:], "asset": ch[1][6:]}}


def parse_sig(data):
    f = _fields(_lines(data, "UCSIG 1"), ("key_id", "ed25519"))
    if not _ID.match(f["key_id"]) or not _HEX128.match(f["ed25519"]):
        raise ManifestError("firma mal formada")
    return f["key_id"], bytes.fromhex(f["ed25519"])


def parse_keyrec(data):
    order = ("seq", "action", "key_id", "role", "pubkey", "channels", "not_before", "signed_by")
    f = _fields(_lines(data, "UCKEYREC 1"), order)
    if not _INT.match(f["seq"]) or f["action"] not in ("add", "revoke", "replace-root"):
        raise ManifestError("seq o action no válidos")
    if f["role"] not in ("root", "release", "recovery", "sandbox"):
        raise ManifestError("role no válido")
    if not _ID.match(f["key_id"]) or not _ID.match(f["signed_by"]) or not _HEX64.match(f["pubkey"]):
        raise ManifestError("key_id, signed_by o pubkey no válidos")
    chans = f["channels"].split(",") if f["channels"] != "-" else []
    if any(c not in CHANNELS for c in chans) or len(set(chans)) != len(chans):
        raise ManifestError("channels no válido")
    if not _DATE.match(f["not_before"]):
        raise ManifestError("not_before no válido")
    return {"seq": int(f["seq"]), "action": f["action"], "key_id": f["key_id"], "role": f["role"],
            "pubkey": bytes.fromhex(f["pubkey"]), "channels": chans,
            "not_before": f["not_before"], "signed_by": f["signed_by"]}


_PKGNAME = re.compile(r"\A[a-z0-9][a-z0-9_.-]{0,63}\Z")
_PKGVER = re.compile(r"\A[0-9A-Za-z][0-9A-Za-z.+~-]{0,31}\Z")
_PKGPATH = re.compile(r"\A(/[A-Za-z0-9_.+-]{1,58}){1,16}\Z")
MAX_PKG_FILES = 512


def parse_pkgmanifest(data):
    """`UCPKG 1` (pkg2, SPEC_UC §8.2): manifiesto firmado de un paquete opcional, con el hash
    de cada fichero. Mismas reglas de gramática que UCMANIFEST (ASCII, orden fijo, `end`)."""
    order = ("name", "version", "channel", "key_id", "depends", "file")
    f = _fields(_lines(data, "UCPKG 1", MAX_PKG_BYTES), order, repeat=("file",))
    if not _PKGNAME.match(f["name"]) or not _PKGVER.match(f["version"]):
        raise ManifestError("nombre o versión de paquete no válidos")
    if f["channel"] not in CHANNELS or not _ID.match(f["key_id"]):
        raise ManifestError("canal o key_id no válidos")
    deps = [] if f["depends"] == "-" else f["depends"].split(" ")
    if any(not _PKGNAME.match(d) for d in deps) or len(set(deps)) != len(deps):
        raise ManifestError("depends no válido")
    files = []
    if len(f["file"]) > MAX_PKG_FILES:
        raise ManifestError("demasiados ficheros")
    for n, line in enumerate(f["file"], 1):
        parts = line.split(" ")
        if len(parts) != 3 or not parts[1].startswith("sha256=") or not parts[2].startswith("size="):
            raise ManifestError("fichero %d: se esperaba '<ruta> sha256=<hex> size=<n>'" % n)
        path, sha, size = parts[0], parts[1][7:], parts[2][5:]
        if not _PKGPATH.match(path) or ".." in path.split("/") or "." in path.split("/"):
            raise ManifestError("fichero %d: ruta no válida" % n)
        if not _HEX64.match(sha) or not _INT.match(size):
            raise ManifestError("fichero %d: hash o tamaño no válidos" % n)
        if path in [x[0] for x in files]:
            raise ManifestError("fichero %d repetido" % n)
        files.append((path, sha, int(size)))
    return {"name": f["name"], "version": f["version"], "channel": f["channel"],
            "key_id": f["key_id"], "depends": deps, "files": files}


def verify_pkgmanifest(data, sig_bytes, keyring):
    m = parse_pkgmanifest(data)
    key_id, sig = parse_sig(sig_bytes)
    if key_id != m["key_id"]:
        raise ManifestError("la firma es de otra clave (%s) que la del paquete" % key_id)
    key = keyring.get(key_id)
    if key is None:
        raise ManifestError("clave desconocida o revocada: %s" % key_id)
    if m["channel"] not in key["channels"]:
        raise ManifestError("la clave %s no puede firmar el canal %s" % (key_id, m["channel"]))
    if not ed25519.verify(key["pubkey"], data, sig):
        raise ManifestError("firma no válida")
    return m


def verify_manifest(manifest_bytes, sig_bytes, keyring):
    """Analiza y verifica. `keyring`: {key_id: {"pubkey": bytes32, "channels": [...]}}.
    Devuelve el manifiesto analizado o lanza ManifestError con el motivo."""
    m = parse_manifest(manifest_bytes)
    key_id, sig = parse_sig(sig_bytes)
    if key_id != m["key_id"]:
        raise ManifestError("la firma es de otra clave (%s) que la del manifiesto" % key_id)
    key = keyring.get(key_id)
    if key is None:
        raise ManifestError("clave desconocida o revocada: %s" % key_id)
    if m["channel"] not in key["channels"]:                     # UC-5
        raise ManifestError("la clave %s no puede firmar el canal %s" % (key_id, m["channel"]))
    if not ed25519.verify(key["pubkey"], manifest_bytes, sig):
        raise ManifestError("firma no válida")
    return m
