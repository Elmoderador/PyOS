"""Códigos de error del kernel (numeración POSIX/Linux, fija: no depende del host)."""

EPERM, ENOENT, ESRCH, EINTR = 1, 2, 3, 4
EIO, EBADF, ECHILD, EAGAIN, ENOMEM = 5, 9, 10, 11, 12
EACCES, EFAULT, EBUSY, EEXIST, EXDEV = 13, 14, 16, 17, 18
ENOTDIR, EISDIR, EINVAL, EMFILE, ENOSPC = 20, 21, 22, 24, 28
ESPIPE, EROFS, EPIPE, ENAMETOOLONG, ENOSYS, ENOTEMPTY = 29, 30, 32, 36, 38, 39
ENOEXEC = 8
EFBIG = 27
ENODEV = 19

NAMES = {v: k for k, v in globals().items() if k.startswith("E") and isinstance(v, int)}


class KError(Exception):
    """Error recuperable de una operación del kernel; se devuelve como -errno."""

    def __init__(self, errno: int, msg: str = ""):
        super().__init__(errno, msg or NAMES.get(errno, str(errno)))
        self.errno = errno


class KernelPanic(Exception):
    pass
