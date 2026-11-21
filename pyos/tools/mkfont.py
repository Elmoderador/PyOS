"""Genera pyos/kernel/drivers/font8x19.py a partir de la fuente de la consola de edk2.

Fuente: MdeModulePkg/Universal/Console/GraphicsConsoleDxe/LaffStd.c (BSD-2-Clause-Patent,
Intel). Es la misma fuente 8x19 que dibuja el firmware, así LOOK y la consola UEFI se
ven iguales. Solo se extraen los datos; no se usa código C.

    python -m pyos.tools.mkfont /ruta/a/edk2
"""
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "kernel" / "drivers" / "font8x19.py"


def parse(edk2):
    edk2 = Path(edk2)
    names = {}
    hdr = (edk2 / "MdePkg/Include/Protocol/SimpleTextOut.h").read_text(encoding="latin-1")
    for m in re.finditer(r"#define\s+([A-Z_]+)\s+0x([0-9a-fA-F]+)", hdr):
        names[m.group(1)] = int(m.group(2), 16)
    src = (edk2 / "MdeModulePkg/Universal/Console/GraphicsConsoleDxe/LaffStd.c").read_text(encoding="latin-1")
    glyphs = {}
    for m in re.finditer(r"\{\s*(\(CHAR16\))?([A-Za-z_0-9]+)\s*,\s*0x[0-9a-fA-F]+\s*,\s*\{([^}]*)\}", src):
        key = m.group(2)
        cp = int(key, 16) if key.startswith("0x") else names[key]
        rows = [int(v, 16) for v in m.group(3).replace(",", " ").split()]
        if len(rows) != 19:
            raise ValueError("glifo %s: %d filas" % (key, len(rows)))
        if cp:
            glyphs[cp] = bytes(rows)
    return glyphs


def main(argv):
    edk2 = argv[1] if len(argv) > 1 else "/home/claude/uefi/edk2"
    glyphs = parse(edk2)
    lines = ['"""Fuente 8x19 de la consola gráfica de edk2 (LaffStd.c, BSD-2-Clause-Patent,',
             'Copyright (c) 2006-2008 Intel Corporation). Generado por pyos/tools/mkfont.py."""',
             "WIDTH, HEIGHT = 8, 19", "GLYPHS = {"]
    for cp in sorted(glyphs):
        lines.append("    0x%04x: %r," % (cp, glyphs[cp]))
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("%d glifos -> %s" % (len(glyphs), OUT))


if __name__ == "__main__":
    main(sys.argv)
