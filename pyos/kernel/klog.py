"""printk / dmesg: registro circular del kernel."""

from collections import deque


class KernelLog:
    def __init__(self, write, clock, capacity: int = 2000, quiet: bool = False):
        self._write = write          # escribe bytes en la consola
        self._clock = clock          # segundos desde el arranque
        self.buf = deque(maxlen=capacity)
        self.quiet = quiet

    def __call__(self, msg: str, level: str = "info") -> None:
        line = f"[{self._clock():9.4f}] {msg}"
        self.buf.append(line)
        if level != "debug" and (not self.quiet or level != "info"):
            self._write((line + "\n").encode("utf-8", "replace"))

    def dump(self) -> str:
        return "\n".join(self.buf) + ("\n" if self.buf else "")
