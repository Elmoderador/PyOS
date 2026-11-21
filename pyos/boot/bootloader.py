"""Bootloader de PyOS (stage 2).

Lee la imagen del kernel de los sectores indicados en el boot record, verifica
su SHA-256, la carga en memoria con un importador propio (el kernel nunca se
importa desde el árbol de fuentes) y salta a kernel_main(bootinfo).
"""
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import linecache
import sys
import zipfile

from .bootrecord import BootRecord

KERNEL_PACKAGE = "pyoskernel"


class BootError(Exception):
    pass


class BootInfo(object):
    """Lo que el bootloader entrega al kernel (como la info de multiboot)."""

    def __init__(self, machine, cmdline, fs_lba, kernel_sha256, kernel_size):
        self.machine = machine
        self.cmdline = cmdline
        self.fs_lba = fs_lba
        self.memory_map = [(0, machine.ram.size, "usable")]
        self.kernel_sha256 = kernel_sha256
        self.kernel_size = kernel_size
        self.loader_name = "PyOS bootloader 1.0"


class ImageImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, image, package):
        self.package = package
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
        exec(compile(src, origin, "exec"), module.__dict__)

    def install(self):
        for name in [m for m in sys.modules if m == self.package or m.startswith(self.package + ".")]:
            del sys.modules[name]
        sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, ImageImporter)]
        sys.meta_path.insert(0, self)


def boot(machine, sector0, say, extra_cmdline=""):
    rec = BootRecord.unpack(sector0)
    say("PyOS bootloader: kernel en LBA %d, %d bytes\n" % (rec.kernel_lba, rec.kernel_size))
    nsect = (rec.kernel_size + 511) // 512
    image = machine.disk.read(rec.kernel_lba, nsect)[:rec.kernel_size]
    digest = hashlib.sha256(image).digest()
    if digest != rec.kernel_sha256:
        raise BootError("imagen del kernel corrupta (SHA-256 no coincide)")
    say("PyOS bootloader: SHA-256 OK %s...\n" % digest.hex()[:16])
    ImageImporter(image, KERNEL_PACKAGE).install()
    kmain = importlib.import_module(KERNEL_PACKAGE + ".main")
    cmdline = (rec.cmdline + " " + extra_cmdline).strip()
    info = BootInfo(machine, cmdline, rec.fs_lba, digest.hex(), rec.kernel_size)
    say("PyOS bootloader: saltando a kernel_main\n")
    return kmain.kernel_main(info)
