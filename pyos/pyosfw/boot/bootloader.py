"""Bootloader de PyOS 2.0 (va dentro de bootloader.zip, en la ESP; lo actualiza UC, D14).

1. Lee el registro de arranque v2 (el válido de mayor secuencia) y el almacén de claves, que
   verifica él mismo desde la clave raíz incluida (UC-36).
2. Elige el conjunto: el activo; si está en prueba, le descuenta un intento; sin intentos, lo
   marca `mala` y vuelve al otro `buena` (UC-41, UC-42).
3. Verifica la firma del manifiesto instalado del conjunto y el SHA-256 del kernel contra él
   (UC-72). El kernel y el sistema salen siempre del MISMO conjunto (UC-73).
4. Importa el kernel (ImageImporter, sin tocar el árbol de fuentes) y le pasa la raíz verity
   del volumen de sistema que dice ese manifiesto.

Si un conjunto no verifica, lo marca `mala` y prueba el otro.
"""
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import linecache
import sys
import zipfile

from ..kernel import anchors
from ..kernel.crypto.manifest import ManifestError, verify_manifest
from ..kernel.update import bootfmt, trust

KERNEL_PACKAGE = "pyoskernel"
LOADER_NAME = "PyOS bootloader 2.0"


class BootError(Exception):
    pass


class BootInfo(object):
    """Lo que el bootloader entrega al kernel (como la info de multiboot)."""

    def __init__(self, machine, cmdline, fs_lba, kernel_sha256, kernel_size, boot=None):
        self.machine = machine
        self.cmdline = cmdline
        self.fs_lba = fs_lba
        self.memory_map = [(0, machine.ram.size, "usable")]
        self.kernel_sha256 = kernel_sha256
        self.kernel_size = kernel_size
        self.loader_name = LOADER_NAME
        self.boot = boot or {}


class ImageImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, image, package, hook=None):
        """hook(module, ruta, código, ejecutar): gancho de las pruebas y de la medida de
        cobertura (machine.kernel_loader_hook); en una máquina real no existe."""
        self.package = package
        self.hook = hook
        zf = zipfile.ZipFile(io.BytesIO(image))
        try:
            self.files = dict((n, zf.read(n)) for n in zf.namelist() if n.endswith(".py"))
        finally:
            zf.close()
        self._paths = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.package and not fullname.startswith(self.package + "."):
            return None
        rel = fullname[len(self.package):].lstrip(".").replace(".", "/")
        cands = [rel + "/__init__.py", rel + ".py"] if rel else ["__init__.py"]
        for cand in cands:
            if cand in self.files:
                is_pkg = cand.endswith("__init__.py")
                spec = importlib.util.spec_from_loader(fullname, self, is_package=is_pkg)
                spec.origin = "pyos-image:/" + cand
                spec.has_location = True
                self._paths[fullname] = cand
                return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        cand = self._paths[module.__name__]
        src = self.files[cand].decode("utf-8")
        origin = module.__spec__.origin
        linecache.cache[origin] = (len(src), None, src.splitlines(True), origin)
        module.__file__ = origin

        def run():
            exec(compile(src, origin, "exec"), module.__dict__)
        if self.hook is not None:
            self.hook(module, cand, src, run)
        else:
            run()

    def install(self):
        for name in [m for m in sys.modules if m == self.package or m.startswith(self.package + ".")]:
            del sys.modules[name]
        sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, ImageImporter)]
        sys.meta_path.insert(0, self)


def load_keyring(disk):
    root, recovery = trust.anchors_from_module(anchors)
    if root is None:
        raise BootError("este bootloader no lleva clave raíz incluida")
    chain, _ = bootfmt.read_keystore(disk)
    return trust.replay(chain, root, recovery)


def _good(rec, i):
    return rec.sets[i].state == bootfmt.STATE_GOOD


def plan(rec, previous=False):
    """Orden de conjuntos a probar y registro modificado (o None si no cambia).
    No escribe: así se puede probar sin disco."""
    new = rec.copy()
    a = new.active
    other = 1 - a
    s = new.sets[a]
    changed = False
    if previous:
        if not _good(new, other):
            raise BootError("no hay una versión anterior buena a la que volver")
        new.active = other
        return [other], new
    if s.state == bootfmt.STATE_TRIAL:
        if s.tries > 0:
            s.tries -= 1
            return [a] + ([other] if _good(new, other) else []), new
        s.state = bootfmt.STATE_BAD                         # UC-42: intentos agotados
        changed = True
        if _good(new, other):
            new.active = other
            return [other], new
        return [], new
    if s.state == bootfmt.STATE_GOOD:
        return [a] + ([other] if _good(new, other) else []), (new if changed else None)
    if _good(new, other):
        new.active = other
        return [other], new
    return [], (new if changed else None)


def check_set(disk, rec, i, keyring):
    """Verifica el conjunto i. Devuelve (manifiesto analizado, bytes, firma, kernel) o BootError."""
    try:
        mbytes, sig = bootfmt.read_set_header(disk, i)
        m = verify_manifest(mbytes, sig, keyring.boot_keys())
    except (bootfmt.FormatError, ManifestError) as e:
        raise BootError("conjunto %s: %s" % (bootfmt.SET_NAMES[i], e))
    name = bootfmt.SET_NAMES[i]
    if m["boot_abi"] > bootfmt.BOOT_ABI:
        raise BootError("conjunto %s: necesita boot_abi %d (este bootloader: %d)"
                        % (name, m["boot_abi"], bootfmt.BOOT_ABI))
    if m["channel"] != rec.sets[i].channel:
        raise BootError("conjunto %s: el canal del manifiesto no es el del registro" % name)
    for comp in ("kernel", "system"):
        if comp not in m["components"] or comp not in m["set"]:
            raise BootError("conjunto %s: el manifiesto no trae %s" % (name, comp))
        if m["components"][comp]["rollback"] < rec.rollback[comp]:
            raise BootError("conjunto %s: %s por debajo del índice anti-retroceso" % (name, comp))
    k = m["components"]["kernel"]
    if not 0 < k["size"] <= bootfmt.kernel_max(i):
        raise BootError("conjunto %s: kernel de tamaño no válido" % name)
    kernel = bytes(disk.read(bootfmt.kernel_lba(i), (k["size"] + 511) // 512))[:k["size"]]
    if hashlib.sha256(kernel).hexdigest() != k["sha256"]:
        raise BootError("conjunto %s: el kernel no coincide con su manifiesto" % name)
    s = m["components"]["system"]
    try:
        nblocks, tblocks = bootfmt.split_system(s["size"])
    except bootfmt.FormatError as e:
        raise BootError("conjunto %s: %s" % (name, e))
    if s["size"] // 512 > rec.sys_sectors:
        raise BootError("conjunto %s: el sistema no cabe en su ranura" % name)
    return m, mbytes, sig, kernel, nblocks


def boot(machine, say, extra_cmdline="", previous=False):
    disk = machine.disk
    rec, errs = bootfmt.read_record(disk)
    if rec is None:
        head = bytes(disk.read(0, 1))
        if head[:8] == bootfmt.MAGIC:
            raise BootError("disco de PyOS 1.x: PyOS 2.0 no lo arranca. Instala un disco 2.0 "
                            "y copia tus datos con 'migrate' (D5)")
        raise BootError("no hay registro de arranque v2 válido (%s)" % "; ".join(errs))
    keyring, kerrs = load_keyring(disk)
    for e in kerrs:
        say("PyOS bootloader: almacén de claves: %s\n" % e)
    order, new = plan(rec, previous)
    if new is not None:
        rec = bootfmt.write_record(disk, new)
    for i in order:
        name = bootfmt.SET_NAMES[i]
        try:
            m, mbytes, sig, kernel, nblocks = check_set(disk, rec, i, keyring)
        except BootError as e:
            say("PyOS bootloader: %s\n" % e)
            bad = rec.copy()
            bad.sets[i].state = bootfmt.STATE_BAD
            if bad.active == i and _good(bad, 1 - i):
                bad.active = 1 - i
            rec = bootfmt.write_record(disk, bad)
            continue
        if rec.active != i:
            fix = rec.copy()
            fix.active = i
            rec = bootfmt.write_record(disk, fix)
        st = rec.sets[i]
        say("PyOS bootloader: conjunto %s (%s, %s%s), kernel %d bytes\n"
            % (name, m["version"], m["channel"],
               ", en prueba: quedan %d intentos" % st.tries if st.state == bootfmt.STATE_TRIAL else "",
               len(kernel)))
        digest = hashlib.sha256(kernel).digest()
        say("PyOS bootloader: firma del manifiesto y SHA-256 OK %s...\n" % digest.hex()[:16])
        sys_lba = bootfmt.sys_lba(rec, i)
        info = {"set": i, "set_name": name, "trial": st.state == bootfmt.STATE_TRIAL,
                "version": m["version"], "channel": m["channel"], "manifest": mbytes, "sig": sig,
                "sys": {"lba": sys_lba, "nblocks": nblocks, "tree_lba": sys_lba + nblocks * 8,
                        "root": bytes.fromhex(m["components"]["system"]["verity"])},
                "data": {"lba": rec.data_lba, "sectors": rec.data_sectors},
                "bootloader": getattr(machine, "boot_copy", None),
                "boot_abi": bootfmt.BOOT_ABI, "anchors_build": getattr(anchors, "BUILD", "?"),
                "keyring_errors": kerrs}
        ImageImporter(kernel, KERNEL_PACKAGE, getattr(machine, "kernel_loader_hook", None)).install()
        kmain = importlib.import_module(KERNEL_PACKAGE + ".main")
        cmdline = (rec.cmdline + " " + extra_cmdline).strip()
        bi = BootInfo(machine, cmdline, rec.data_lba, digest.hex(), len(kernel), info)
        say("PyOS bootloader: saltando a kernel_main\n")
        return kmain.kernel_main(bi)
    raise BootError("ningún conjunto de arranque es válido")


def previous_available(disk):
    """True si el menú puede ofrecer 'versión anterior' (UC-61)."""
    rec, _ = bootfmt.read_record(disk)
    return rec is not None and _good(rec, 1 - rec.active) and _good(rec, rec.active)
