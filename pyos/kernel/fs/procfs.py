"""procfs (/proc): vista de solo lectura del estado real del kernel, generada al abrir."""

from ..errors import KError, EACCES, EISDIR, ENOENT, ENOTDIR, EROFS
from .vfs import FileOps, O_ACCMODE, O_RDONLY


class _Snapshot(FileOps):
    def __init__(self, data: bytes):
        self.data = data

    def read(self, of, n):
        chunk = self.data[of.offset:of.offset + n]
        of.offset += len(chunk)
        return chunk

    def size(self):
        return len(self.data)


class ProcFS:
    name = "procfs"
    GLOBAL = ("meminfo", "uptime", "interrupts", "mounts", "devices", "version",
              "cmdline", "stat", "filesystems", "cpuinfo", "pci", "linux", "gfx", "net")
    PERPROC = ("status", "maps", "cmdline", "fd", "stack")

    def __init__(self, kernel):
        self.k = kernel

    def _pid(self, s: str):
        if s == "self":
            return self.k.current.pid if self.k.current else 0
        if s.isdigit() and int(s) in self.k.procs:
            return int(s)
        return None

    def _content(self, parts) -> str:
        k = self.k
        if len(parts) == 1 and parts[0] in self.GLOBAL:
            return getattr(k, "proc_" + parts[0])()
        if len(parts) == 2:
            pid = self._pid(parts[0])
            if pid is not None and parts[1] in self.PERPROC:
                return k.proc_process_file(k.procs[pid], parts[1])
        raise KError(ENOENT)

    def open(self, parts, flags):
        if (flags & O_ACCMODE) != O_RDONLY:
            raise KError(EACCES)
        if self._isdir(parts):
            raise KError(EISDIR)
        return _Snapshot(self._content(parts).encode("utf-8"))

    def _isdir(self, parts) -> bool:
        return not parts or (len(parts) == 1 and self._pid(parts[0]) is not None)

    def stat(self, parts):
        if self._isdir(parts):
            return {"type": "dir", "size": 0, "ino": 0, "links": 2, "mtime": 0, "ctime": 0, "fs": self.name}
        size = len(self._content(parts).encode("utf-8"))
        return {"type": "file", "size": size, "ino": 0, "links": 1, "mtime": 0, "ctime": 0, "fs": self.name}

    def readdir(self, parts):
        if not parts:
            return [(n, "file") for n in self.GLOBAL] + \
                   [(str(p), "dir") for p in sorted(self.k.procs)] + [("self", "dir")]
        if len(parts) == 1 and self._pid(parts[0]) is not None:
            return [(n, "file") for n in self.PERPROC]
        if self._content(parts) is not None:
            raise KError(ENOTDIR)
        raise KError(ENOENT)  # pragma: no cover

    def mkdir(self, parts):
        raise KError(EROFS)

    rmdir = unlink = mkdir

    def rename(self, a, b):
        raise KError(EROFS)

    def sync(self):
        pass
