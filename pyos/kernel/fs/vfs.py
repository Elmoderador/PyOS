"""VFS: tabla de montaje, resolución de rutas y ficheros abiertos."""


from ..errors import KError, EBADF, EBUSY, EINVAL, ENAMETOOLONG, ENOENT, ESPIPE, EXDEV

O_RDONLY, O_WRONLY, O_RDWR = 0, 1, 2
O_ACCMODE = 3
O_CREAT, O_EXCL, O_TRUNC, O_APPEND = 0x40, 0x80, 0x200, 0x400
O_NONBLOCK = 0x800
SEEK_SET, SEEK_CUR, SEEK_END = 0, 1, 2
MAX_PATH = 1024
MAX_NAME = 58


class FileOps:
    """Operaciones de un fichero abierto. Las subclasses implementan lo que soporten."""
    seekable = True

    def read(self, of, n: int) -> bytes:
        raise KError(EBADF)

    def write(self, of, data: bytes) -> int:
        raise KError(EBADF)

    def size(self) -> int:
        return 0

    def close(self, of) -> None:
        pass


class OpenFile:
    """Descripción de fichero abierto (compartida entre fds heredados)."""

    def __init__(self, ops: FileOps, flags: int, path: str):
        self.ops = ops
        self.flags = flags
        self.path = path
        self.offset = 0
        self.refs = 1

    @property
    def readable(self) -> bool:
        return (self.flags & O_ACCMODE) in (O_RDONLY, O_RDWR)

    @property
    def writable(self) -> bool:
        return (self.flags & O_ACCMODE) in (O_WRONLY, O_RDWR)

    def read(self, n: int) -> bytes:
        if not self.readable:
            raise KError(EBADF, "no abierto para lectura")
        return self.ops.read(self, n)

    def write(self, data: bytes) -> int:
        if not self.writable:
            raise KError(EBADF, "no abierto para escritura")
        return self.ops.write(self, data)

    def seek(self, off: int, whence: int) -> int:
        if not self.ops.seekable:
            raise KError(ESPIPE)
        base = {SEEK_SET: 0, SEEK_CUR: self.offset, SEEK_END: self.ops.size()}.get(whence)
        if base is None or base + off < 0:
            raise KError(EINVAL)
        self.offset = base + off
        return self.offset

    def dup(self) -> "OpenFile":
        self.refs += 1
        return self

    def close(self) -> None:
        self.refs -= 1
        if self.refs == 0:
            self.ops.close(self)


def normpath(path, cwd="/"):
    """Normalización de rutas POSIX propia (sin depender del módulo os del host)."""
    full = path if path.startswith("/") else cwd.rstrip("/") + "/" + path
    out = []
    for part in full.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/" + "/".join(out)


def dirname(path):
    head = path.rsplit("/", 1)[0]
    return head or "/"


def basename(path):
    return path.rsplit("/", 1)[-1]


def check_name(name: str) -> None:
    if name in ("", ".", "..") or "/" in name or "\0" in name:
        raise KError(EINVAL, f"nombre inválido: {name!r}")
    if len(name.encode("utf-8")) > MAX_NAME:
        raise KError(ENAMETOOLONG)


class VFS:
    def __init__(self):
        self.mounts: dict = {}

    def mount(self, mountpoint: str, fs) -> None:
        self.mounts[mountpoint] = fs

    def normalize(self, path: str, cwd: str = "/") -> str:
        if not isinstance(path, str) or not path:
            raise KError(ENOENT)
        if len(path) > MAX_PATH:
            raise KError(ENAMETOOLONG)
        return normpath(path, cwd)

    def resolve(self, path: str, cwd: str = "/"):
        p = self.normalize(path, cwd)
        best = "/"
        for mp in self.mounts:
            if mp != "/" and (p == mp or p.startswith(mp + "/")) and len(mp) > len(best):
                best = mp
        rel = p if best == "/" else p[len(best):]
        return self.mounts[best], [x for x in rel.split("/") if x], p

    def open(self, path, flags, cwd="/") -> OpenFile:
        fs, parts, p = self.resolve(path, cwd)
        return OpenFile(fs.open(parts, flags), flags, p)

    def stat(self, path, cwd="/") -> dict:
        fs, parts, _ = self.resolve(path, cwd)
        return fs.stat(parts)

    def readdir(self, path, cwd="/") -> list:
        fs, parts, p = self.resolve(path, cwd)
        entries = fs.readdir(parts)
        names = {n for n, _ in entries}
        for mp in self.mounts:
            if mp != "/" and dirname(mp) == p and basename(mp) not in names:
                entries.append((basename(mp), "dir"))
        return sorted(entries)

    def _not_mountpoint(self, p: str) -> None:
        if p in self.mounts:
            raise KError(EBUSY, "es un punto de montaje")

    def mkdir(self, path, cwd="/") -> None:
        fs, parts, _ = self.resolve(path, cwd)
        fs.mkdir(parts)

    def rmdir(self, path, cwd="/") -> None:
        fs, parts, p = self.resolve(path, cwd)
        self._not_mountpoint(p)
        fs.rmdir(parts)

    def unlink(self, path, cwd="/") -> None:
        fs, parts, p = self.resolve(path, cwd)
        self._not_mountpoint(p)
        fs.unlink(parts)

    def rename(self, old, new, cwd="/") -> None:
        fa, pa, a = self.resolve(old, cwd)
        fb, pb, b = self.resolve(new, cwd)
        self._not_mountpoint(a)
        self._not_mountpoint(b)
        if fa is not fb:
            raise KError(EXDEV)
        fa.rename(pa, pb)

    def sync(self) -> None:
        for fs in self.mounts.values():
            fs.sync()
