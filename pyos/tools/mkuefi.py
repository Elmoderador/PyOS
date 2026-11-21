"""Construye el disco arrancable de PyOS para UEFI, SIN Linux.

Contenido del disco (GPT, una partición EFI FAT32):
    \\EFI\\BOOT\\BOOTX64.EFI   UEFI Shell (TianoCore, compilado de fuentes oficiales)
    \\EFI\\Tools\\Python.efi   CPython 3.6.8 para UEFI (edk2-libc, compilado de fuentes)
    \\EFI\\StdLib\\...         biblioteca estándar de ese Python
    \\startup.nsh             localiza la partición y lanza PyOS
    \\pyos\\start.py           entrada de PyOS (HAL de hardware real + firmware PyOS)
    \\pyos\\pyos\\{boot,hal}    firmware/bootloader y drivers de la máquina
    \\pyos\\disk.img           disco de PyOS: boot record + kernel + PyFS + userland

Salidas: .img (raw, QEMU), .vdi (VirtualBox), .vhdx (Hyper-V), .vmdk (VMware).

Uso (Linux/WSL2, como root para compilar edk2):
    python -m pyos.tools.mkuefi build/uefi            # compila Python.efi/Shell.efi si faltan
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import mkimage

PKG = Path(__file__).resolve().parent.parent
EDK2_TAG = "edk2-stable202505"
ESP_MB = 160
PYOS_DISK_MB = 64
STDLIB_PRUNE = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
                "pydoc_data", "distutils", "unittest", "sqlite3", "asyncio", "concurrent",
                "multiprocessing", "xmlrpc", "wsgiref", "http", "email", "xml", "json",
                "urllib", "ctypes", "curses", "dbm", "venv", "msilib", "html"]

STARTUP_NSH = r"""@echo -off
cls
echo Buscando PyOS...
for %a in 0 1 2 3 4 5 6 7 8 9
  if exist fs%a:\pyos\start.py then
    fs%a:
    cd \pyos
    \EFI\Tools\Python.efi start.py
    goto FIN
  endif
endfor
echo No se encontro la particion de PyOS.
:FIN
"""


def sh(*args, **kw):
    print("  $", " ".join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], check=True, **kw)


def build_python_efi(work):
    """Compila Python.efi (edk2-libc) y Shell.efi (edk2) desde las fuentes oficiales."""
    work = Path(work)
    edk2, libc = work / "edk2", work / "edk2-libc"
    if not edk2.exists():
        sh("git", "clone", "-q", "--depth", "1", "--branch", EDK2_TAG,
           "https://github.com/tianocore/edk2.git", edk2)
        sh("git", "-C", edk2, "submodule", "update", "--init", "--depth", "1")
    if not libc.exists():
        sh("git", "clone", "-q", "--depth", "1", "https://github.com/tianocore/edk2-libc.git", libc)
    py = libc / "AppPkg/Applications/Python/Python-3.6.8"
    sh(sys.executable, "srcprep.py", cwd=py, stdout=subprocess.DEVNULL)
    sh("make", "-C", edk2 / "BaseTools", "-j2", stdout=subprocess.DEVNULL)
    env = dict(os.environ, PACKAGES_PATH="%s:%s" % (edk2, libc), EDK2_LIBC_PATH=str(libc))
    script = ("source edksetup.sh >/dev/null && "
              "build -a X64 -b RELEASE -t GCC -p AppPkg/AppPkg.dsc -D BUILD_PYTHON368 -n 2 && "
              "build -a X64 -b RELEASE -t GCC -p ShellPkg/ShellPkg.dsc -n 2")
    sh("bash", "-c", script, cwd=edk2, env=env, stdout=subprocess.DEVNULL)


def locate(work):
    work = Path(work)
    edk2, libc = work / "edk2", work / "edk2-libc"
    out = {
        "python": edk2 / "Build/AppPkg/RELEASE_GCC/X64/Python.efi",
        "shell": edk2 / "Build/Shell/RELEASE_GCC/X64/ShellPkg/Application/Shell/Shell/OUTPUT/Shell.efi",
        "lib": libc / "AppPkg/Applications/Python/Python-3.6.8/Lib",
        "etc": libc / "StdLib/Efi/StdLib/etc",
    }
    return out if all(p.exists() for p in out.values()) else None


def _copy_tree(src, dst, ignore=None):
    shutil.copytree(str(src), str(dst), ignore=ignore)


def build_esp_tree(tree, parts, cmdline):
    if tree.exists():
        shutil.rmtree(str(tree))
    (tree / "EFI/BOOT").mkdir(parents=True)
    (tree / "EFI/Tools").mkdir(parents=True)
    shutil.copy(str(parts["shell"]), str(tree / "EFI/BOOT/BOOTX64.EFI"))
    shutil.copy(str(parts["python"]), str(tree / "EFI/Tools/Python.efi"))
    _copy_tree(parts["lib"], tree / "EFI/StdLib/lib/python36.8",
               ignore=shutil.ignore_patterns("__pycache__", *STDLIB_PRUNE))
    _copy_tree(parts["etc"], tree / "EFI/StdLib/etc")
    (tree / "startup.nsh").write_bytes(STARTUP_NSH.replace("\n", "\r\n").encode("ascii"))
    pyos_dir = tree / "pyos"
    (pyos_dir / "pyos").mkdir(parents=True)
    # licencias de lo que va en la imagen (Apache-2.0 de PyOS + edk2/CPython)
    lic = tree / "LICENSES"
    lic.mkdir(parents=True, exist_ok=True)
    root = PKG.parent
    for f in ("LICENSE", "NOTICE"):
        if (root / f).exists():
            shutil.copy(str(root / f), str(lic / f))
    if (root / "licenses").is_dir():
        for f in sorted((root / "licenses").iterdir()):
            shutil.copy(str(f), str(lic / f.name))
    shutil.copy(str(PKG / "uefi/start.py"), str(pyos_dir / "start.py"))
    shutil.copy(str(PKG / "__init__.py"), str(pyos_dir / "pyos/__init__.py"))
    for sub in ("boot", "hal"):
        _copy_tree(PKG / sub, pyos_dir / "pyos" / sub, ignore=shutil.ignore_patterns("__pycache__", "emulated.py"))
    mkimage.build(str(pyos_dir / "disk.img"), PYOS_DISK_MB, cmdline)


def build_disk(out_dir, work=None, cmdline=mkimage.DEFAULT_CMDLINE, formats=("vdi", "vhdx", "vmdk")):
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(work or out_dir / "work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    parts = locate(work)
    if parts is None:
        print("[1/4] compilando Python.efi y Shell.efi (edk2)")
        build_python_efi(work)
        parts = locate(work)
    else:
        print("[1/4] Python.efi y Shell.efi ya compilados")
    print("[2/4] árbol de la partición EFI")
    tree = work / "esp"
    build_esp_tree(tree, parts, cmdline)
    print("[3/4] FAT32 + GPT")
    esp = work / "esp.fat"
    if esp.exists():
        esp.unlink()
    with open(str(esp), "wb") as f:
        f.truncate(ESP_MB << 20)
    sh("mkfs.vfat", "-F", "32", "-n", "PYOS", esp, stdout=subprocess.DEVNULL)
    sh("mcopy", "-s", "-i", esp, *sorted(str(p) for p in tree.iterdir()), "::/")
    raw = out_dir / "pyos-uefi.img"
    total = (ESP_MB + 2) << 20
    with open(str(raw), "wb") as f:
        f.truncate(total)
    first = 2048
    last = first + (ESP_MB << 20) // 512 - 1
    sh("sgdisk", "-o", "-n", "1:%d:%d" % (first, last), "-t", "1:ef00", "-c", "1:PyOS EFI", raw,
       stdout=subprocess.DEVNULL)
    with open(str(raw), "r+b") as dst, open(str(esp), "rb") as src:
        dst.seek(first * 512)
        shutil.copyfileobj(src, dst, 1 << 20)
    print("[4/4] formatos de máquina virtual")
    outs = {"img": raw}
    names = {"vdi": "vdi", "vhdx": "vhdx", "vmdk": "vmdk"}
    for fmt in formats:
        dst = out_dir / ("pyos-uefi." + fmt)
        if dst.exists():
            dst.unlink()
        sh("qemu-img", "convert", "-O", names[fmt], raw, dst)
        outs[fmt] = dst
    return outs


if __name__ == "__main__":
    res = build_disk(sys.argv[1] if len(sys.argv) > 1 else "build/uefi",
                     work=sys.argv[2] if len(sys.argv) > 2 else None)
    for k, v in res.items():
        print("%-5s %s (%d MiB)" % (k, v, v.stat().st_size >> 20))
