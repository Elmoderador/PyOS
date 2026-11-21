"""Tuberías anónimas: buffer en el kernel con lectores/escritores bloqueantes."""
from ..errors import KError, EAGAIN, EINTR, EPIPE
from ..proc.process import SIGPIPE, Block, WaitQueue
from .vfs import O_NONBLOCK, FileOps

PIPE_BUF = 4096


class Pipe(object):
    def __init__(self, kernel):
        self.k = kernel
        self.buf = bytearray()
        self.readers = 0
        self.writers = 0
        self.wq = WaitQueue(kernel, "pipe")


class PipeReader(FileOps):
    seekable = False

    def __init__(self, pipe):
        self.p = pipe
        pipe.readers += 1

    def read(self, of, n):
        p = self.p
        if not p.buf:
            if p.writers == 0:
                return b""
            if of.flags & O_NONBLOCK:
                raise KError(EAGAIN)
            if p.k.current.pending_signals:
                raise KError(EINTR)
            raise Block(p.wq)
        data = bytes(p.buf[:n])
        del p.buf[:len(data)]
        p.wq.wake_all()
        return data

    def close(self, of):
        self.p.readers -= 1
        self.p.wq.wake_all()


class PipeWriter(FileOps):
    seekable = False

    def __init__(self, pipe):
        self.p = pipe
        pipe.writers += 1

    def write(self, of, data):
        """Escritura atómica hasta PIPE_BUF; si no cabe, bloquea y se reintenta."""
        p, k = self.p, self.p.k
        if p.readers == 0:
            k.send_signal(k.current, SIGPIPE)
            raise KError(EPIPE)
        space = PIPE_BUF - len(p.buf)
        if space <= 0 or (len(data) <= PIPE_BUF and space < len(data)):
            if k.current.pending_signals:
                raise KError(EINTR)
            raise Block(p.wq)
        chunk = bytes(data[:space])
        p.buf += chunk
        p.wq.wake_all()
        gfx = getattr(k, "gfx", None)
        if gfx is not None:
            gfx.notify()                # LOOK puede estar esperando la salida de un terminal
        return len(chunk)

    def close(self, of):
        self.p.writers -= 1
        self.p.wq.wake_all()
        gfx = getattr(self.p.k, "gfx", None)
        if gfx is not None:
            gfx.notify()
