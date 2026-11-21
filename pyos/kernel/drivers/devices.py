"""Gestor de dispositivos: registro de drivers, números major/minor e IRQs."""


class CharDevice:
    name = "?"
    major = 0
    minor = 0
    irq = None
    description = ""

    def open(self, flags):
        raise NotImplementedError


class DeviceManager:
    def __init__(self, log):
        self.log = log
        self._devs: dict = {}

    def register(self, dev: CharDevice) -> None:
        if dev.name in self._devs:
            raise ValueError(f"dispositivo duplicado: {dev.name}")
        self._devs[dev.name] = dev
        irq = f" irq {dev.irq}" if dev.irq is not None else ""
        self.log(f"dev: {dev.name} ({dev.major},{dev.minor}){irq} {dev.description}")

    def get(self, name: str):
        return self._devs.get(name)

    def names(self) -> list:
        return sorted(self._devs)

    def all(self) -> list:
        return [self._devs[n] for n in self.names()]
