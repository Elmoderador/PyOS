"""devfs (/dev): expone los dispositivos de carácter registrados."""

from ..errors import KError, ENOENT, ENOTDIR, EPERM


class DevFS:
    name = "devfs"

    def __init__(self, devices):
        self.devices = devices  # DeviceManager

    def _get(self, parts):
        if len(parts) != 1:
            raise KError(ENOENT if len(parts) > 1 else ENOTDIR)
        dev = self.devices.get(parts[0])
        if dev is None:
            raise KError(ENOENT)
        return dev

    def open(self, parts, flags):
        return self._get(parts).open(flags)

    def stat(self, parts):
        if not parts:
            return {"type": "dir", "size": 0, "ino": 0, "links": 2, "mtime": 0, "ctime": 0, "fs": self.name}
        d = self._get(parts)
        return {"type": "chr", "size": 0, "ino": d.minor, "links": 1, "mtime": 0, "ctime": 0,
                "fs": self.name, "major": d.major, "minor": d.minor}

    def readdir(self, parts):
        if parts:
            raise KError(ENOTDIR)
        return [(name, "chr") for name in self.devices.names()]

    def mkdir(self, parts):
        raise KError(EPERM)

    rmdir = unlink = mkdir

    def rename(self, a, b):
        raise KError(EPERM)

    def sync(self):
        pass
