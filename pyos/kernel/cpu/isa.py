"""Juego de instrucciones de la CPU virtual de PyOS (PVM).

Máquina de pila. Cada instrucción es (opcode, argumento). Los programas de
usuario se compilan desde Python a este ISA; la PVM los ejecuta con marcos
explícitos, lo que permite suspender un proceso en CUALQUIER instrucción.
"""
import operator

_NAMES = """
NOP LOAD_CONST LOAD_FAST STORE_FAST DELETE_FAST LOAD_DEREF STORE_DEREF
LOAD_GLOBAL STORE_GLOBAL DELETE_GLOBAL LOAD_CLASSNAME STORE_CLASSNAME
LOAD_ATTR STORE_ATTR DELETE_ATTR LOAD_SUBSCR STORE_SUBSCR DELETE_SUBSCR
BINARY INPLACE UNARY COMPARE
POP DUP DUP2 ROT2 ROT3
JUMP POP_JUMP_IF_FALSE POP_JUMP_IF_TRUE JUMP_IF_FALSE_OR_POP JUMP_IF_TRUE_OR_POP
BUILD_TUPLE BUILD_LIST BUILD_SET BUILD_MAP BUILD_SLICE BUILD_STRING FORMAT
LIST_APPEND SET_ADD MAP_ADD LIST_EXTEND SET_UPDATE DICT_UPDATE
UNPACK UNPACK_EX GET_ITER FOR_ITER
CALL CALL_EX MAKE_FUNCTION MAKE_CLASS RETURN YIELD
SETUP_LOOP SETUP_EXCEPT SETUP_FINALLY POP_BLOCK POP_EXCEPT END_FINALLY
UNWIND_JUMP RAISE EXC_MATCH SETUP_WITH WITH_EXIT LOAD_EXC
LOAD_FAST2 LOAD_FAST_ATTR LOAD_FAST_CONST BINARY_CONST COMPARE_JUMP_FALSE
STORE_LOAD_FAST INPLACE_STORE_FAST
""".split()

for _i, _n in enumerate(_NAMES):
    globals()[_n] = _i
OPNAMES = list(_NAMES)
NUM_OPS = len(_NAMES)

BINOPS = [operator.add, operator.sub, operator.mul, operator.truediv, operator.floordiv,
          operator.mod, operator.pow, operator.lshift, operator.rshift, operator.or_,
          operator.xor, operator.and_, operator.matmul]
BINOP_INDEX = {"Add": 0, "Sub": 1, "Mult": 2, "Div": 3, "FloorDiv": 4, "Mod": 5, "Pow": 6,
               "LShift": 7, "RShift": 8, "BitOr": 9, "BitXor": 10, "BitAnd": 11, "MatMult": 12}
INPLACE_OPS = [operator.iadd, operator.isub, operator.imul, operator.itruediv,
               operator.ifloordiv, operator.imod, operator.ipow, operator.ilshift,
               operator.irshift, operator.ior, operator.ixor, operator.iand, operator.imatmul]
UNARYOPS = [operator.neg, operator.pos, operator.not_, operator.invert]
UNARY_INDEX = {"USub": 0, "UAdd": 1, "Not": 2, "Invert": 3}


def _in(a, b):
    return a in b


def _not_in(a, b):
    return a not in b


CMPOPS = [operator.eq, operator.ne, operator.lt, operator.le, operator.gt, operator.ge,
          operator.is_, operator.is_not, _in, _not_in]
CMP_INDEX = {"Eq": 0, "NotEq": 1, "Lt": 2, "LtE": 3, "Gt": 4, "GtE": 5, "Is": 6,
             "IsNot": 7, "In": 8, "NotIn": 9}

# Tipos de bloque en tiempo de ejecución
B_LOOP, B_EXCEPT, B_FINALLY, B_HANDLER, B_WITH = 1, 2, 3, 4, 5


class Code(object):
    """Unidad compilada: módulo, función, lambda o cuerpo de clase."""

    __slots__ = ("name", "filename", "ops", "args", "lines", "consts", "nlocals", "varnames",
                 "cellvars", "freevars", "argcount", "kwonly", "vararg", "kwarg", "is_gen",
                 "cell_of_arg", "firstline", "kind", "simple")

    def __init__(self, name, filename, kind):
        self.name = name
        self.filename = filename
        self.kind = kind            # "module" | "function" | "class"
        self.ops = []
        self.args = []
        self.lines = []
        self.consts = []
        self.nlocals = 0
        self.varnames = []
        self.cellvars = []
        self.freevars = []
        self.argcount = 0
        self.kwonly = []
        self.vararg = None
        self.kwarg = None
        self.is_gen = False
        self.cell_of_arg = []       # [(indice_arg, indice_celda)]
        self.firstline = 0
        self.simple = False         # sin *args/**kw/kwonly: paso de argumentos rápido

    def __deepcopy__(self, memo):
        return self                 # el código es inmutable: compartido entre fork()s

    def __repr__(self):
        return "<code %s %s:%d>" % (self.name, self.filename, self.firstline)

    def disassemble(self):
        out = []
        for i, (op, arg) in enumerate(zip(self.ops, self.args)):
            out.append("%4d %-4d %-20s %r" % (self.lines[i], i, OPNAMES[op], arg))
        return "\n".join(out)
