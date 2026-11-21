"""Formato del sector de arranque (LBA 0) de un disco PyOS."""

import struct

MAGIC = b"PYOSBOOT"
VERSION = 1
SIGNATURE = b"\x55\xaa"
_FMT = "<8sHII32sI128s"  # magic, version, kernel_lba, kernel_size, sha256, fs_lba, cmdline


class BootRecordError(Exception):
    pass


class BootRecord(object):
    def __init__(self, kernel_lba, kernel_size, kernel_sha256, fs_lba, cmdline):
        self.kernel_lba = kernel_lba
        self.kernel_size = kernel_size
        self.kernel_sha256 = kernel_sha256
        self.fs_lba = fs_lba
        self.cmdline = cmdline

    def pack(self):
        cmd = self.cmdline.encode("utf-8")
        if len(cmd) > 127:
            raise BootRecordError("cmdline demasiado larga (máx 127 bytes)")
        body = struct.pack(_FMT, MAGIC, VERSION, self.kernel_lba, self.kernel_size,
                           self.kernel_sha256, self.fs_lba, cmd)
        return body.ljust(510, b"\0") + SIGNATURE

    @classmethod
    def unpack(cls, sector):
        if len(sector) != 512 or sector[510:512] != SIGNATURE:
            raise BootRecordError("sin firma de arranque 0x55AA")
        magic, ver, klba, ksize, sha, fslba, cmd = struct.unpack_from(_FMT, sector)
        if magic != MAGIC:
            raise BootRecordError("no es un disco PyOS")
        if ver != VERSION:
            raise BootRecordError(f"versión de boot record no soportada: {ver}")
        return cls(klba, ksize, sha, fslba, cmd.rstrip(b"\0").decode("utf-8"))
