"""Construcción de la imagen de disco de PyOS.

Disposición del disco:
    LBA 0                  boot record (firma 0x55AA)
    LBA 1 ..               imagen del kernel (zip de pyos/kernel), SHA-256 en el boot record
    LBA FS_LBA ..          partición PyFS (formateada con el MISMO driver que usa el kernel)
"""

import hashlib
import io
import os
import time
import zipfile
from pathlib import Path

from ..boot.bootrecord import BootRecord
from ..hal.emulated import FileDisk as DiskController
from ..kernel.fs.buffercache import BufferCache
from ..kernel.fs.pyfs import BLOCK, PyFS
from ..kernel.errors import EEXIST, KError
from ..kernel.fs.vfs import O_CREAT, O_TRUNC, O_WRONLY, OpenFile

PKG = Path(__file__).resolve().parent.parent
KERNEL_DIR = PKG / "kernel"
USERLAND_DIR = PKG / "userland"
FS_LBA = 8192                      # 4 MiB reservados para boot + kernel
DEFAULT_CMDLINE = "init=/sbin/init.py quantum=5 hz=100 kbd=es"
SKELETON = ["bin", "sbin", "lib", "etc", "etc/svc", "dev", "proc", "tmp", "root", "home",
            "var", "var/log", "var/run", "var/pkg", "var/pkg/repo", "var/pkg/db"]
PACKAGES_DIR = Path(__file__).resolve().parent.parent / "packages"
# Configuración del usuario: 'update' no la pisa si ya existe.
CONFIG_PREFIXES = ("/etc/",)
DEFAULT_PACKAGES = ("arcade", "look")     # vienen instalados (y registrados en /var/pkg/db)


def build_kernel_image() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(KERNEL_DIR.rglob("*.py")):
            rel = path.relative_to(KERNEL_DIR).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))  # imagen reproducible
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def write_kernel(disk: DiskController, cmdline: str) -> BootRecord:
    image = build_kernel_image()
    nsect = (len(image) + 511) // 512
    if 1 + nsect > FS_LBA:
        raise RuntimeError("el kernel no cabe en el área reservada")
    disk.write(1, image.ljust(nsect * 512, b"\0"))
    rec = BootRecord(1, len(image), hashlib.sha256(image).digest(), FS_LBA, cmdline)
    disk.write(0, rec.pack())
    disk.flush()
    return rec


def _mount(disk: DiskController) -> PyFS:
    nblocks = (disk.sectors - FS_LBA) * 512 // BLOCK
    return BufferCache(disk, FS_LBA, BLOCK, nblocks)


def _ensure_dirs(fs: PyFS, parts) -> None:
    for i in range(1, len(parts)):
        try:
            fs.mkdir(parts[:i])
        except KError as e:
            if e.errno != EEXIST:
                raise


def _exists(fs: PyFS, dest: str) -> bool:
    try:
        fs.stat([p for p in dest.split("/") if p])
        return True
    except KError:
        return False


def install_file(fs: PyFS, dest: str, data: bytes) -> None:
    parts = [p for p in dest.split("/") if p]
    _ensure_dirs(fs, parts)
    of = OpenFile(fs.open(parts, O_WRONLY | O_CREAT | O_TRUNC), O_WRONLY, dest)
    try:
        of.write(data)
    finally:
        of.close()


def install_userland(fs: PyFS, keep_config: bool = False) -> int:
    n = 0
    for path in sorted(USERLAND_DIR.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        dest = "/" + path.relative_to(USERLAND_DIR).as_posix()
        if keep_config and dest.startswith(CONFIG_PREFIXES) and _exists(fs, dest):
            continue
        install_file(fs, dest, path.read_bytes())
        n += 1
    for name, data in build_packages().items():
        install_file(fs, "/var/pkg/repo/" + name, data)
        n += 1
    n += install_default_packages(fs)
    return n


def install_default_packages(fs: PyFS) -> int:
    """Instala los paquetes por defecto igual que lo haría 'pkg install'."""
    n = 0
    for d in sorted(p for p in PACKAGES_DIR.iterdir() if p.is_dir() and p.name in DEFAULT_PACKAGES):
        meta = _pkginfo(d)
        files = _pkgfiles(d)
        for dest, data in files.items():
            install_file(fs, dest, data)
            n += 1
        rec = "".join("%s: %s\n" % (k, meta.get(k, "")) for k in ("name", "version", "description", "depends"))
        rec += "".join(p + "\n" for p in sorted(files))
        install_file(fs, "/var/pkg/db/" + meta["name"], rec.encode("utf-8"))
    return n


def _pkginfo(d: Path) -> dict:
    meta = {}
    for line in (d / "PKGINFO").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    if meta.get("name") != d.name:
        raise ValueError("PKGINFO de %s: name no coincide" % d.name)
    return meta


def _pkgfiles(d: Path) -> dict:
    files = {}
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.name != "PKGINFO" and "__pycache__" not in f.parts:
            files["/" + f.relative_to(d).as_posix()] = f.read_bytes()
    return files


# ------------------------------------------------------------------ paquetes
def pack(meta: dict, files: dict) -> bytes:
    """Formato PYOSPKG 1: cabecera de texto + entradas 'file <ruta> <bytes>' + datos."""
    out = [b"PYOSPKG 1\n"]
    for key in ("name", "version", "description", "depends"):
        out.append(("%s: %s\n" % (key, meta.get(key, ""))).encode("utf-8"))
    for dest in sorted(files):
        data = files[dest]
        out.append(("file %s %d\n" % (dest, len(data))).encode("utf-8"))
        out.append(data)
        out.append(b"\n")
    out.append(b"end\n")
    return b"".join(out)


def build_packages(src: Path = PACKAGES_DIR) -> dict:
    """pyos/packages/<nombre>/PKGINFO + árbol de ficheros -> {'nombre-ver.pkg': bytes}."""
    result = {}
    if not src.is_dir():
        return result
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        meta = _pkginfo(d)
        result["%s-%s.pkg" % (meta["name"], meta["version"])] = pack(meta, _pkgfiles(d))
    return result


def _populate(disk: DiskController, nblocks: int, cmdline: str) -> dict:
    rec = write_kernel(disk, cmdline)
    cache = BufferCache(disk, FS_LBA, BLOCK, nblocks)
    PyFS.format(cache, time.time)
    fs = PyFS(cache, time.time)
    for d in SKELETON:
        fs.mkdir(d.split("/"))
    nfiles = install_userland(fs)
    fs.unmount()
    st = fs.statfs()
    return {"kernel_bytes": rec.kernel_size, "files": nfiles,
            "free_blocks": st["free_blocks"], "blocks": st["blocks"]}


def build(image_path: str, size_mb: int = 32, cmdline: str = DEFAULT_CMDLINE) -> dict:
    """Crea un fichero imagen nuevo de `size_mb` MiB."""
    size = size_mb * 1024 * 1024
    if size // 512 <= FS_LBA + 1024:
        raise ValueError("imagen demasiado pequeña (mínimo ~5 MiB)")
    with open(image_path, "wb") as f:
        f.truncate(size)
    disk = DiskController(image_path)
    try:
        info = _populate(disk, (disk.sectors - FS_LBA) * 512 // BLOCK, cmdline)
    finally:
        disk.close()
    return {"image": image_path, **info}


def install_to_device(dev_path: str, fs_mb: int = 256, cmdline: str = DEFAULT_CMDLINE) -> dict:
    """Instala PyOS en un disco existente (p. ej. /dev/sda de una VM). Borra su contenido.
    La partición PyFS se limita a `fs_mb` MiB aunque el disco sea mayor."""
    disk = DiskController(dev_path)
    try:
        avail = (disk.sectors - FS_LBA) * 512 // BLOCK
        nblocks = min(avail, fs_mb * 1024 * 1024 // BLOCK)
        if nblocks < 256:
            raise ValueError("disco demasiado pequeño (mínimo ~5 MiB)")
        info = _populate(disk, nblocks, cmdline)
    finally:
        disk.close()
    return {"device": dev_path, **info}


def update(image_path, cmdline=None, userland=True):
    """Reinstala kernel (y opcionalmente /bin, /sbin, /lib) sin borrar los datos del usuario."""
    disk = DiskController(image_path)
    try:
        old = BootRecord.unpack(disk.read(0, 1))
        rec = write_kernel(disk, cmdline or old.cmdline)
        nfiles = 0
        if userland:
            fs = PyFS(_mount(disk), time.time)
            nfiles = install_userland(fs, keep_config=True)
            fs.unmount()
    finally:
        disk.close()
    return {"image": image_path, "kernel_bytes": rec.kernel_size, "files": nfiles}


def fsck(image_path: str) -> dict:
    """Comprueba y repara la partición PyFS de una imagen (con el sistema apagado)."""
    disk = DiskController(image_path)
    try:
        fs = PyFS(_mount(disk), time.time)
        report = fs.fsck(repair=True)
        fs.unmount()
    finally:
        disk.close()
    return report


if __name__ == "__main__":  # pragma: no cover
    print(build(os.environ.get("PYOS_IMAGE", "pyos.img")))
