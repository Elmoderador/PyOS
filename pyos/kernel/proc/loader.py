"""Cargador de programas: fuente Python -> código PVM, con caché por SHA-256.

Los programas de usuario se ejecutan en la PVM, no en el intérprete del host:
el aislamiento lo da la propia CPU virtual (atributos internos opacos, sin
import, builtins mínimos, syscalls como única salida).
"""
import builtins
import hashlib

from ..cpu.compiler import CompileError, compile_source
from ..errors import KError, ENOEXEC

SAFE_BUILTINS = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable", "chr",
    "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset", "hash", "hex",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "type", "zip", "True", "False", "None", "NotImplemented", "Ellipsis",
    "Exception", "ArithmeticError", "AssertionError", "AttributeError", "EOFError",
    "IndexError", "KeyError", "LookupError", "MemoryError", "NameError", "NotImplementedError",
    "OSError", "OverflowError", "RecursionError", "RuntimeError", "StopIteration",
    "TypeError", "UnicodeDecodeError", "UnicodeEncodeError", "ValueError", "ZeroDivisionError",
    "BrokenPipeError", "FileNotFoundError", "FileExistsError", "IsADirectoryError",
    "NotADirectoryError", "PermissionError", "InterruptedError", "ProcessLookupError",
    "ChildProcessError", "UnboundLocalError", "KeyboardInterrupt", "SyntaxError",
]


def build_builtins():
    b = {}
    for name in SAFE_BUILTINS:
        if hasattr(builtins, name):
            b[name] = getattr(builtins, name)
    return b


class Loader(object):
    def __init__(self, limit=64):
        self._cache = {}
        self.limit = limit
        self.hits = self.misses = 0

    def load(self, source, path):
        key = hashlib.sha256(source).hexdigest()
        code = self._cache.get(key)
        if code is not None:
            self.hits += 1
            return code
        self.misses += 1
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as e:
            raise KError(ENOEXEC, "%s: %s" % (path, e))
        try:
            code = compile_source(text, path)
        except CompileError as e:
            raise KError(ENOEXEC, str(e))
        if len(self._cache) >= self.limit:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = code
        return code
