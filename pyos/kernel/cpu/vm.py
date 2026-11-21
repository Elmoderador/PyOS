"""PVM: la CPU virtual de PyOS.

Cada proceso tiene su propia PVM: una pila de marcos explícitos (sin recursión
del host para llamadas entre funciones de usuario), así que el kernel puede:
  - detener el proceso tras N instrucciones (apropiación exacta),
  - atrapar las syscalls como una instrucción especial (trap real),
  - copiar el estado entero del proceso (fork real),
  - garantizar que el código de usuario solo toca lo que la PVM le deja tocar.
"""
import copy

from .isa import (
    LOAD_FAST2, LOAD_FAST_ATTR, LOAD_FAST_CONST, BINARY_CONST, COMPARE_JUMP_FALSE,
    STORE_LOAD_FAST, INPLACE_STORE_FAST,
    NOP, LOAD_CONST, LOAD_FAST, STORE_FAST, DELETE_FAST, LOAD_DEREF, STORE_DEREF,
    LOAD_GLOBAL, STORE_GLOBAL, DELETE_GLOBAL, LOAD_CLASSNAME, STORE_CLASSNAME,
    LOAD_ATTR, STORE_ATTR, DELETE_ATTR, LOAD_SUBSCR, STORE_SUBSCR, DELETE_SUBSCR,
    BINARY, INPLACE, UNARY, COMPARE, POP, DUP, DUP2, ROT2, ROT3,
    JUMP, POP_JUMP_IF_FALSE, POP_JUMP_IF_TRUE, JUMP_IF_FALSE_OR_POP, JUMP_IF_TRUE_OR_POP,
    BUILD_TUPLE, BUILD_LIST, BUILD_SET, BUILD_MAP, BUILD_SLICE, BUILD_STRING, FORMAT,
    LIST_APPEND, SET_ADD, MAP_ADD, LIST_EXTEND, SET_UPDATE, DICT_UPDATE,
    UNPACK, UNPACK_EX, GET_ITER, FOR_ITER, CALL, CALL_EX, MAKE_FUNCTION, MAKE_CLASS,
    RETURN, YIELD, SETUP_LOOP, SETUP_EXCEPT, SETUP_FINALLY, POP_BLOCK, POP_EXCEPT,
    END_FINALLY, UNWIND_JUMP, RAISE, EXC_MATCH, SETUP_WITH, WITH_EXIT,
    BINOPS, INPLACE_OPS, UNARYOPS, CMPOPS, B_LOOP, B_EXCEPT, B_FINALLY, B_HANDLER, B_WITH,
)

MAX_FRAMES = 400
FORBIDDEN_ATTRS = frozenset(["mro", "format_map"])
FORBIDDEN_PREFIXES = ("__", "_pvm", "gi_", "f_", "tb_", "co_", "cr_", "ag_")

# Resultados de run()
R_BUDGET, R_SYSCALL, R_EXIT, R_ERROR = 0, 1, 2, 3


class Cell(object):
    __slots__ = ("v",)
    _EMPTY = object()

    def __init__(self, v=_EMPTY):
        self.v = v


class SyscallGate(object):
    """El único objeto que permite salir de la PVM hacia el kernel."""
    __slots__ = ("pid",)

    def __init__(self, pid):
        self.pid = pid

    def __call__(self, *args):
        raise RuntimeError("syscall fuera de la PVM")

    def __deepcopy__(self, memo):
        return memo.get("__gate__", self)


class _Marker(object):
    """Evento pendiente que un bloque finally debe reanudar."""
    __slots__ = ("kind", "a", "b", "c")

    def __init__(self, kind, a=None, b=None, c=None):
        self.kind, self.a, self.b, self.c = kind, a, b, c


class Block(object):
    __slots__ = ("kind", "handler", "depth", "saved", "has_iter")

    def __init__(self, kind, handler, depth, saved=None, has_iter=0):
        self.kind, self.handler, self.depth, self.saved, self.has_iter = kind, handler, depth, saved, has_iter


class Frame(object):
    __slots__ = ("code", "pc", "stack", "fast", "cells", "globals", "blocks", "cur_exc",
                 "classdict", "gen", "mode", "aux")

    def __init__(self, code, globals_, fast=None, cells=None, classdict=None):
        self.code = code
        self.pc = 0
        self.stack = []
        self.fast = fast if fast is not None else [Cell._EMPTY] * code.nlocals
        self.cells = cells if cells is not None else []
        self.globals = globals_
        self.blocks = []
        self.cur_exc = None
        self.classdict = classdict
        self.gen = None
        self.mode = None     # None | "iter" | "class" | "init" | "send"
        self.aux = None


class VMFunction(object):
    __slots__ = ("code", "globals", "defaults", "kwdefaults", "closure", "name", "vm_owner", "__weakref__")

    def __init__(self, code, globals_, defaults, kwdefaults, closure):
        self.code = code
        self.globals = globals_
        self.defaults = defaults
        self.kwdefaults = kwdefaults
        self.closure = closure
        self.name = code.name

    def __repr__(self):
        return "<function %s>" % self.name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return VMBoundMethod(self, obj)

    def __call__(self, *args, **kwargs):
        """Llamada desde código del host (p. ej. sorted(key=...)): ejecución anidada."""
        return nested_call(self, args, kwargs)


class VMBoundMethod(object):
    __slots__ = ("func", "self_")

    def __init__(self, func, self_):
        self.func, self.self_ = func, self_

    def __call__(self, *args, **kwargs):
        return nested_call(self.func, (self.self_,) + args, kwargs)

    def __repr__(self):
        return "<bound method %s>" % self.func.name


class VMGenerator(object):
    __slots__ = ("frame", "running", "done", "name")

    def __init__(self, frame, name):
        self.frame, self.running, self.done, self.name = frame, False, False, name

    def __iter__(self):
        return self

    def __next__(self):
        if self.done:
            raise StopIteration
        return nested_resume(self)

    def __repr__(self):
        return "<generator %s>" % self.name


class GuestError(Exception):
    """Excepción no capturada en el proceso de usuario."""

    def __init__(self, exc, tb):
        Exception.__init__(self, exc)
        self.exc, self.tb = exc, tb


# ------------------------------------------------------------------ ejecución anidada
_nested_ctx = []   # pila de (vm) activos, para llamadas host->usuario


def nested_call(func, args, kwargs):
    vm = _nested_ctx[-1] if _nested_ctx else None
    if vm is None:
        raise RuntimeError("función de usuario llamada fuera de su proceso")
    sub = PVM(vm.builtins, vm.gate, vm.syscall_handler, vm.attr_guard)
    sub.frames.append(sub.make_frame(func, list(args), kwargs or {}))
    return sub.run_nested()


def nested_resume(gen):
    vm = _nested_ctx[-1] if _nested_ctx else None
    if vm is None:
        raise RuntimeError("generador de usuario fuera de su proceso")
    sub = PVM(vm.builtins, vm.gate, vm.syscall_handler, vm.attr_guard)
    f = gen.frame
    f.mode, f.aux = "send", None
    gen.running = True
    f.stack.append(None) if f.pc > 0 else None
    sub.frames.append(f)
    try:
        v = sub.run_nested(gen=gen)
    finally:
        gen.running = False
    if gen.done:
        raise StopIteration
    return v


SAFE_DUNDERS = frozenset(["__name__", "__qualname__", "__doc__", "__module__"])


def check_attr(name):
    if name in SAFE_DUNDERS:
        return
    if name.startswith(FORBIDDEN_PREFIXES) or name in FORBIDDEN_ATTRS:
        raise AttributeError("acceso al atributo '%s' denegado por la PVM" % name)


class _Done(Exception):
    pass


class PVM(object):
    """Contexto de ejecución de un proceso."""

    def __init__(self, builtins_, gate, syscall_handler=None, attr_guard=check_attr):
        self.builtins = builtins_
        self.gate = gate
        self.syscall_handler = syscall_handler   # para syscalls en contexto anidado
        self.attr_guard = attr_guard
        self.frames = []
        self.result = None
        self.icount = 0
        self.pending = None          # args de la syscall atrapada

    # ------------------------------------------------------------------ marcos
    def make_frame(self, func, args, kwargs):
        code = func.code
        n = code.argcount
        if code.simple and not kwargs and len(args) == n:
            # caso más común: solo posicionales, número exacto
            fast = list(args)
            if code.nlocals > n:
                fast.extend([Cell._EMPTY] * (code.nlocals - n))
            return self._finish_frame(func, code, fast)
        fast = [Cell._EMPTY] * code.nlocals
        if len(args) > n:
            if code.vararg is None:
                raise TypeError("%s() recibe %d argumentos posicionales pero se dieron %d"
                                % (code.name, n, len(args)))
            fast[n] = tuple(args[n:])
        elif code.vararg is not None:
            fast[n] = ()
        for i in range(min(n, len(args))):
            fast[i] = args[i]
        names = code.varnames
        extra = {}
        if kwargs:
            for k, v in kwargs.items():
                try:
                    i = names.index(k)
                except ValueError:
                    i = -1
                if 0 <= i < n or k in code.kwonly:
                    if fast[i] is not Cell._EMPTY:
                        raise TypeError("%s() recibió varios valores para '%s'" % (code.name, k))
                    fast[i] = v
                elif code.kwarg is not None:
                    extra[k] = v
                else:
                    raise TypeError("%s() no acepta el argumento '%s'" % (code.name, k))
        defaults = func.defaults
        nd = len(defaults)
        for i in range(n):
            if fast[i] is Cell._EMPTY:
                j = i - (n - nd)
                if j >= 0:
                    fast[i] = defaults[j]
                else:
                    raise TypeError("%s() falta el argumento '%s'" % (code.name, names[i]))
        base = n + (1 if code.vararg is not None else 0)
        for j, k in enumerate(code.kwonly):
            i = base + j
            if fast[i] is Cell._EMPTY:
                if k in func.kwdefaults:
                    fast[i] = func.kwdefaults[k]
                else:
                    raise TypeError("%s() falta el argumento '%s'" % (code.name, k))
        if code.kwarg is not None:
            fast[base + len(code.kwonly)] = extra
        return self._finish_frame(func, code, fast)

    @staticmethod
    def _finish_frame(func, code, fast):
        if code.cellvars or func.closure:
            cells = [Cell() for _ in code.cellvars] + list(func.closure)
            for ai, ci in code.cell_of_arg:
                cells[ci].v = fast[ai]
        else:
            cells = []
        return Frame(code, func.globals, fast, cells)

    def push_call(self, func, args, kwargs, caller):
        """Llamada a una función de usuario sin recursión del host."""
        if len(self.frames) >= MAX_FRAMES:
            raise RecursionError("profundidad máxima de llamadas superada en la PVM")
        f = self.make_frame(func, args, kwargs)
        if func.code.is_gen:
            g = VMGenerator(f, func.name)
            f.gen = g
            caller.stack.append(g)
            return None
        self.frames.append(f)
        return f

    # ------------------------------------------------------------------ llamada genérica
    def call(self, frame, fn, args, kwargs):
        """Devuelve el marco nuevo si hay que entrar en él, o None si ya dejó el resultado."""
        t = type(fn)
        if t is VMFunction:
            return self.push_call(fn, args, kwargs, frame)
        if t is VMBoundMethod:
            return self.push_call(fn.func, [fn.self_] + list(args), kwargs, frame)
        if t is SyscallGate:
            self.pending = tuple(args)
            raise _Trap()
        if fn in _OPAQUE:
            raise TypeError("no se pueden construir objetos internos de la PVM")
        if getattr(fn, "_pvm_class", False) and isinstance(fn, type):
            init = fn.__dict__.get("__init__") if "__init__" in fn.__dict__ else None
            if init is None:
                for klass in fn.__mro__[1:]:
                    if "__init__" in klass.__dict__:
                        init = klass.__dict__["__init__"]
                        break
            obj = fn.__new__(fn) if not issubclass(fn, BaseException) else fn.__new__(fn, *args)
            if type(init) is VMFunction:
                f = self.push_call(init, [obj] + list(args), kwargs, frame)
                f.mode, f.aux = "init", obj
                return f
            if issubclass(fn, BaseException):
                BaseException.__init__(obj, *args)
            frame.stack.append(obj)
            return None
        _nested_ctx.append(self)
        try:
            frame.stack.append(fn(*args, **kwargs) if kwargs else fn(*args))
        finally:
            _nested_ctx.pop()
        return None

    # ------------------------------------------------------------------ bucle principal
    def run(self, budget):
        """Ejecuta hasta `budget` instrucciones. Devuelve (código, valor)."""
        _nested_ctx.append(self)
        try:
            return self._run(budget)
        finally:
            _nested_ctx.pop()

    def _run(self, budget):
        frames = self.frames
        icount = 0
        while True:
            if not frames:
                self.icount += icount
                return R_EXIT, self.result
            f = frames[-1]
            try:
                icount = self._exec(f, budget - icount, icount)
                if icount >= budget:
                    self.icount += icount
                    return R_BUDGET, None
            except _Trap:
                self.icount += icount
                return R_SYSCALL, self.pending
            except _Done:
                self.icount += icount
                return R_EXIT, self.result
            except BaseException as e:      # también KeyboardInterrupt/SystemExit del usuario
                try:
                    self._unwind(e)
                except GuestError as ge:
                    self.icount += icount
                    return R_ERROR, ge

    def resume_with(self, value):
        """Reanuda tras una syscall: el resultado aparece como valor de la llamada."""
        self.frames[-1].stack.append(value)

    def run_nested(self, gen=None):
        """Ejecuta hasta el final (llamada host->usuario). Las syscalls se sirven en línea."""
        self._nested_gen = gen
        while True:
            code, val = self.run(1 << 30)
            if code == R_EXIT:
                return val
            if code == R_ERROR:
                raise val.exc
            if code == R_SYSCALL:
                if self.syscall_handler is None:
                    raise RuntimeError("syscall en contexto anidado no permitida")
                self.resume_with(self.syscall_handler(val))

    # ------------------------------------------------------------------ excepciones
    def _unwind(self, exc):
        tb = getattr(exc, "_pvm_tb", None)
        if tb is None:
            tb = []
            try:
                exc._pvm_tb = tb
            except (AttributeError, TypeError):
                pass
        frames = self.frames
        while frames:
            f = frames[-1]
            pc = max(f.pc - 1, 0)
            tb.append((f.code.filename, f.code.lines[pc] if f.code.lines else 0, f.code.name))
            while f.blocks:
                b = f.blocks.pop()
                if b.kind == B_EXCEPT:
                    del f.stack[b.depth:]
                    f.blocks.append(Block(B_HANDLER, 0, b.depth, f.cur_exc))
                    f.cur_exc = exc
                    f.stack.append(exc)
                    f.pc = b.handler
                    return
                if b.kind in (B_FINALLY, B_WITH):
                    del f.stack[b.depth:]
                    f.stack.append(_Marker("exc", exc))
                    f.pc = b.handler
                    return
                if b.kind == B_HANDLER:
                    f.cur_exc = b.saved
                del f.stack[b.depth:]
            frames.pop()
            if f.gen is not None:
                f.gen.done = True
            if f.mode == "iter" and frames and isinstance(exc, StopIteration):
                pass
        raise GuestError(exc, list(reversed(tb)))

    def _return(self, f, value):
        """RETURN con desenrollado de finally."""
        while f.blocks:
            b = f.blocks.pop()
            if b.kind in (B_FINALLY, B_WITH):
                del f.stack[b.depth:]
                f.stack.append(_Marker("ret", value))
                f.pc = b.handler
                return
            if b.kind == B_HANDLER:
                f.cur_exc = b.saved
            del f.stack[b.depth:]
        frames = self.frames
        frames.pop()
        mode = f.mode
        if f.gen is not None:
            f.gen.done = True
            if mode == "iter":
                caller = frames[-1]
                caller.stack.pop()          # el iterador
                caller.pc = f.aux
                return
            if mode == "send":
                raise _Done()               # StopIteration en ejecución anidada
            return
        if mode == "signal":
            return                          # el manejador de señal no devuelve nada
        if mode == "init":
            value = f.aux
        elif mode == "class":
            value = self._build_class(f)
        if not frames:
            self.result = value
            raise _Done()
        frames[-1].stack.append(value)

    def _unwind_jump(self, f, target, keep, cont):
        while len(f.blocks) > keep:
            b = f.blocks.pop()
            if b.kind in (B_FINALLY, B_WITH):
                del f.stack[b.depth:]
                f.stack.append(_Marker("jump", target, keep, cont))
                f.pc = b.handler
                return
            if b.kind == B_HANDLER:
                f.cur_exc = b.saved
            del f.stack[b.depth:]
        if cont and f.blocks:
            lb = f.blocks[-1]
            del f.stack[lb.depth + lb.has_iter:]
        f.pc = target

    def _end_finally(self, f, m):
        if m is None:
            return
        if m.kind == "exc":
            raise m.a
        if m.kind == "ret":
            self._return(f, m.a)
        elif m.kind == "jump":
            self._unwind_jump(f, m.a, m.b, m.c)

    def _build_class(self, f):
        name, bases = f.aux
        ns = {}
        for k, v in f.classdict.items():
            ns[k] = v
        if not bases:
            bases = (object,)
        ns["_pvm_class"] = True
        ns.setdefault("__module__", "__pvm__")
        return type(name, bases, ns)

    # ------------------------------------------------------------------ intérprete
    def _exec(self, f, budget, icount):
        frames = self.frames
        code = f.code
        ops, args = code.ops, code.args
        stack = f.stack
        push, pop = stack.append, stack.pop
        fast = f.fast
        pc = f.pc
        guard = self.attr_guard
        fast_guard = guard is check_attr        # LOAD_FAST_ATTR ya se validó al compilar
        builtins_ = self.builtins
        empty = Cell._EMPTY
        limit = icount + budget
        try:
            while icount < limit:
                op = ops[pc]
                arg = args[pc]
                pc += 1
                icount += 1
                if op == LOAD_FAST:
                    v = fast[arg]
                    if v is empty:
                        raise UnboundLocalError("variable local '%s' usada antes de asignarse" % code.varnames[arg])
                    push(v)
                elif op == LOAD_GLOBAL:
                    g = f.globals
                    if arg in g:
                        push(g[arg])
                    elif arg in builtins_:
                        push(builtins_[arg])
                    else:
                        raise NameError("el nombre '%s' no está definido" % arg)
                elif op == LOAD_CONST:
                    push(arg)
                elif op == LOAD_FAST_ATTR:              # x.attr con x local (p. ej. self.x)
                    o = fast[arg[0]]
                    if o is empty:
                        raise UnboundLocalError("variable local '%s' usada antes de asignarse" % code.varnames[arg[0]])
                    if not fast_guard:
                        guard(arg[1])
                    if type(o) in _OPAQUE:
                        raise AttributeError("objeto interno de la PVM")
                    push(getattr(o, arg[1]))
                    pc += 1
                elif op == BINARY:
                    b = pop()
                    stack[-1] = BINOPS[arg](stack[-1], b)
                elif op == CALL:
                    n, kwnames = arg
                    if kwnames:
                        nk = len(kwnames)
                        kwvals = stack[-nk:]
                        del stack[-nk:]
                        kwargs = dict(zip(kwnames, kwvals))
                    else:
                        kwargs = None
                    if n:
                        a = stack[-n:]
                        del stack[-n:]
                    else:
                        a = []
                    fn = pop()
                    f.pc = pc
                    nf = self.call(f, fn, a, kwargs)
                    if nf is not None:
                        # cambio de marco sin salir del bucle (más barato que volver a _run)
                        f = nf
                        code = f.code
                        ops, args = code.ops, code.args
                        stack = f.stack
                        push, pop = stack.append, stack.pop
                        fast = f.fast
                        pc = f.pc
                elif op == STORE_GLOBAL:
                    f.globals[arg] = pop()
                elif op == JUMP:
                    pc = arg
                elif op == STORE_FAST:
                    fast[arg] = pop()
                elif op == LOAD_FAST_CONST:
                    v = fast[arg[0]]
                    if v is empty:
                        raise UnboundLocalError("variable local '%s' usada antes de asignarse" % code.varnames[arg[0]])
                    push(v)
                    push(arg[1])
                    pc += 1
                elif op == FOR_ITER:
                    it = stack[-1]
                    if type(it) is VMGenerator:
                        if it.done:
                            pop()
                            pc = arg
                            continue
                        if it.running:
                            raise ValueError("el generador ya se está ejecutando")
                        gf = it.frame
                        gf.mode, gf.aux, gf.gen = "iter", arg, it
                        if gf.pc > 0:
                            gf.stack.append(None)   # valor de send()
                        it.running = True
                        f.pc = pc
                        self.frames.append(gf)
                        return icount
                    try:
                        push(next(it))
                    except StopIteration:
                        pop()
                        pc = arg
                elif op == STORE_LOAD_FAST:
                    fast[arg[0]] = pop()
                    v = fast[arg[1]]
                    if v is empty:
                        raise UnboundLocalError("variable local '%s' usada antes de asignarse" % code.varnames[arg[1]])
                    push(v)
                    pc += 1
                elif op == BUILD_TUPLE:
                    if arg:
                        t = tuple(stack[-arg:])
                        del stack[-arg:]
                    else:
                        t = ()
                    push(t)
                elif op == LOAD_SUBSCR:
                    i = pop()
                    stack[-1] = stack[-1][i]
                elif op == COMPARE_JUMP_FALSE:
                    b = pop()
                    if CMPOPS[arg[0]](pop(), b):
                        pc += 1
                    else:
                        pc = arg[1]
                elif op == INPLACE:
                    b = pop()
                    stack[-1] = INPLACE_OPS[arg](stack[-1], b)
                elif op == LOAD_ATTR:
                    if arg[:2] == "__" and arg not in SAFE_DUNDERS:
                        # Base.__init__(self, ...) en clases de la PVM: solo si lo que se
                        # obtiene es código de la PVM (nunca un método interno del host).
                        o = stack[-1]
                        if isinstance(o, type) and getattr(o, "_pvm_class", False):
                            v = getattr(o, arg, None)
                            if type(v) is VMFunction:
                                stack[-1] = v
                                continue
                    guard(arg)
                    o = pop()
                    if type(o) in _OPAQUE:
                        raise AttributeError("objeto interno de la PVM")
                    push(getattr(o, arg))
                elif op == LOAD_FAST2:
                    a, b = fast[arg[0]], fast[arg[1]]
                    if a is empty or b is empty:
                        raise UnboundLocalError("variable local '%s' usada antes de asignarse" % code.varnames[arg[0] if a is empty else arg[1]])
                    push(a)
                    push(b)
                    pc += 1
                elif op == RETURN:
                    f.pc = pc
                    self._return(f, pop())
                    if not frames:
                        return icount
                    f = frames[-1]
                    code = f.code
                    ops, args = code.ops, code.args
                    stack = f.stack
                    push, pop = stack.append, stack.pop
                    fast = f.fast
                    pc = f.pc
                elif op == UNPACK:
                    v = pop()
                    if type(v) is VMGenerator:
                        v = self._drain(v)
                    t = tuple(v)
                    if len(t) != arg:
                        raise ValueError("se esperaban %d valores para desempaquetar, hay %d" % (arg, len(t)))
                    stack.extend(reversed(t))
                elif op == POP:
                    pop()
                elif op == BINARY_CONST:
                    stack[-1] = BINOPS[arg[0]](stack[-1], arg[1])
                    pc += 1
                elif op == POP_JUMP_IF_FALSE:
                    if not pop():
                        pc = arg
                elif op == STORE_ATTR:
                    if arg in SAFE_DUNDERS:
                        raise AttributeError("atributo de solo lectura en la PVM")
                    guard(arg)
                    o = pop()
                    if type(o) in _OPAQUE:
                        raise AttributeError("objeto interno de la PVM")
                    setattr(o, arg, pop())
                elif op == DUP:
                    push(stack[-1])
                elif op == ROT2:
                    stack[-1], stack[-2] = stack[-2], stack[-1]
                elif op == BUILD_MAP:
                    d = {}
                    if arg:
                        items = stack[-2 * arg:]
                        del stack[-2 * arg:]
                        for i in range(0, 2 * arg, 2):
                            d[items[i]] = items[i + 1]
                    push(d)
                elif op == COMPARE:
                    b = pop()
                    stack[-1] = CMPOPS[arg](stack[-1], b)
                elif op == JUMP_IF_TRUE_OR_POP:
                    if stack[-1]:
                        pc = arg
                    else:
                        pop()
                elif op == GET_ITER:
                    v = stack[-1]
                    if type(v) is not VMGenerator:
                        stack[-1] = iter(v)
                elif op == INPLACE_STORE_FAST:
                    b = pop()
                    fast[arg[1]] = INPLACE_OPS[arg[0]](pop(), b)
                    pc += 1
                elif op == POP_JUMP_IF_TRUE:
                    if pop():
                        pc = arg
                elif op == UNARY:
                    stack[-1] = UNARYOPS[arg](stack[-1])
                elif op == STORE_SUBSCR:
                    i = pop()
                    o = pop()
                    o[i] = pop()
                elif op == JUMP_IF_FALSE_OR_POP:
                    if not stack[-1]:
                        pc = arg
                    else:
                        pop()
                elif op == LOAD_DEREF:
                    v = f.cells[arg].v
                    if v is empty:
                        raise NameError("variable libre usada antes de asignarse")
                    push(v)
                elif op == STORE_DEREF:
                    f.cells[arg].v = pop()
                elif op == BUILD_LIST:
                    if arg:
                        t = stack[-arg:]
                        del stack[-arg:]
                    else:
                        t = []
                    push(t)
                elif op == BUILD_SET:
                    if arg:
                        t = set(stack[-arg:])
                        del stack[-arg:]
                    else:
                        t = set()
                    push(t)
                elif op == BUILD_SLICE:
                    if arg == 3:
                        st = pop()
                        hi = pop()
                        stack[-1] = slice(stack[-1], hi, st)
                    else:
                        hi = pop()
                        stack[-1] = slice(stack[-1], hi)
                elif op == BUILD_STRING:
                    s = "".join(stack[-arg:]) if arg else ""
                    if arg:
                        del stack[-arg:]
                    push(s)
                elif op == FORMAT:
                    conv, has_spec = arg
                    spec = pop() if has_spec else ""
                    v = pop()
                    if conv == 115:
                        v = str(v)
                    elif conv == 114:
                        v = repr(v)
                    elif conv == 97:
                        v = ascii(v)
                    push(format(v, spec))
                elif op == LIST_APPEND:
                    v = pop()
                    stack[-arg].append(v)
                elif op == SET_ADD:
                    v = pop()
                    stack[-arg].add(v)
                elif op == MAP_ADD:
                    v = pop()
                    k = pop()
                    stack[-arg][k] = v
                elif op == LIST_EXTEND:
                    v = pop()
                    if type(v) is VMGenerator:
                        v = self._drain(v)
                    stack[-arg].extend(v)
                elif op == SET_UPDATE:
                    v = pop()
                    stack[-arg].update(v)
                elif op == DICT_UPDATE:
                    v = pop()
                    stack[-arg].update(v)
                elif op == UNPACK_EX:
                    before, after = arg
                    t = list(pop())
                    if len(t) < before + after:
                        raise ValueError("no hay suficientes valores para desempaquetar")
                    mid = t[before:len(t) - after]
                    vals = t[:before] + [mid] + t[len(t) - after:]
                    stack.extend(reversed(vals))
                elif op == ROT3:
                    v = pop()
                    stack.insert(-2, v)
                elif op == DUP2:
                    stack.extend(stack[-2:])
                elif op == DELETE_ATTR:
                    guard(arg)
                    delattr(pop(), arg)
                elif op == DELETE_SUBSCR:
                    i = pop()
                    del stack[-1][i]
                    pop()
                elif op == DELETE_FAST:
                    fast[arg] = empty
                elif op == DELETE_GLOBAL:
                    del f.globals[arg]
                elif op == LOAD_CLASSNAME:
                    if arg in f.classdict:
                        push(f.classdict[arg])
                    elif arg in f.globals:
                        push(f.globals[arg])
                    elif arg in builtins_:
                        push(builtins_[arg])
                    else:
                        raise NameError("el nombre '%s' no está definido" % arg)
                elif op == STORE_CLASSNAME:
                    f.classdict[arg] = pop()
                elif op == CALL_EX:
                    kwargs = pop()
                    a = pop()
                    fn = pop()
                    f.pc = pc
                    if self.call(f, fn, list(a), kwargs) is not None:
                        return icount
                elif op == MAKE_FUNCTION:
                    fcode, closure_idx = arg
                    kwd = pop()
                    defaults = pop()
                    closure = tuple(f.cells[i] for i in closure_idx)
                    push(VMFunction(fcode, f.globals, defaults, kwd, closure))
                elif op == MAKE_CLASS:
                    name, ccode, closure_idx = arg
                    bases = pop()
                    for b in bases:
                        if not isinstance(b, type):
                            raise TypeError("las bases de una clase deben ser clases")
                    cells = [f.cells[i] for i in closure_idx]
                    cf = Frame(ccode, f.globals, [], cells, classdict={})
                    cf.mode, cf.aux = "class", (name, bases)
                    f.pc = pc
                    if len(self.frames) >= MAX_FRAMES:
                        raise RecursionError("demasiada profundidad")
                    self.frames.append(cf)
                    return icount
                elif op == YIELD:
                    v = pop()
                    f.pc = pc
                    self.frames.pop()
                    gen = f.gen
                    gen.running = False
                    if f.mode == "iter":
                        self.frames[-1].stack.append(v)
                        return icount
                    self.result = v
                    raise _Done()
                elif op == SETUP_LOOP:
                    f.blocks.append(Block(B_LOOP, 0, len(stack) - arg, None, arg))
                elif op == SETUP_EXCEPT:
                    f.blocks.append(Block(B_EXCEPT, arg, len(stack)))
                elif op == SETUP_FINALLY:
                    f.blocks.append(Block(B_FINALLY, arg, len(stack)))
                elif op == POP_BLOCK:
                    f.blocks.pop()
                elif op == POP_EXCEPT:
                    b = f.blocks.pop()
                    f.cur_exc = b.saved
                    del stack[b.depth:]
                elif op == END_FINALLY:
                    m = pop()
                    if m is not None:
                        f.pc = pc
                        self._end_finally(f, m)
                        return icount
                elif op == UNWIND_JUMP:
                    f.pc = pc
                    self._unwind_jump(f, arg[0], arg[1], arg[2])
                    return icount
                elif op == RAISE:
                    if arg == 0:
                        if f.cur_exc is None:
                            raise RuntimeError("no hay excepción activa que relanzar")
                        raise f.cur_exc
                    if arg == 3:
                        e = pop()
                        b = f.blocks.pop()
                        f.cur_exc = b.saved
                        del stack[b.depth:]
                        raise e
                    cause = pop() if arg == 2 else None
                    e = pop()
                    if isinstance(e, type) and issubclass(e, BaseException):
                        e = e()
                    if not isinstance(e, BaseException):
                        raise TypeError("solo se pueden lanzar excepciones")
                    if arg == 2:
                        e.__cause__ = cause
                    raise e
                elif op == EXC_MATCH:
                    t = pop()
                    e = stack[-1]
                    stack[-1] = isinstance(e, t)
                elif op == SETUP_WITH:
                    mgr = pop()
                    exitf = mgr.__exit__
                    enter = mgr.__enter__
                    push(exitf)
                    f.blocks.append(Block(B_WITH, arg, len(stack)))
                    _nested_ctx.append(self)
                    try:
                        push(enter())
                    finally:
                        _nested_ctx.pop()
                elif op == WITH_EXIT:
                    m = pop()
                    exitf = pop()
                    _nested_ctx.append(self)
                    try:
                        if m is not None and m.kind == "exc":
                            e = m.a
                            if exitf(type(e), e, None):
                                m = None
                        else:
                            exitf(None, None, None)
                    finally:
                        _nested_ctx.pop()
                    if m is not None:
                        f.pc = pc
                        self._end_finally(f, m)
                        return icount
                elif op == NOP:
                    pass
                else:
                    raise SystemError("opcode desconocido %r" % op)
            f.pc = pc
            return icount
        except BaseException:
            f.pc = pc
            self.icount += 0
            raise

    def _drain(self, gen):
        _nested_ctx.append(self)
        try:
            return list(gen)
        finally:
            _nested_ctx.pop()


class _Trap(Exception):
    pass


_OPAQUE = (VMFunction, VMBoundMethod, VMGenerator, Frame, Cell, SyscallGate, Block, _Marker)


def fork_state(vm, new_gate, extra=None):
    """Copia profunda del estado de un proceso (fork real).

    Se copian todos los marcos y todo lo alcanzable desde ellos (variables,
    listas, generadores, funciones...). El código y los builtins se comparten
    porque son inmutables. Devuelve (pvm_hija, copia_de_extra).
    """
    memo = {"__gate__": new_gate, id(vm.builtins): vm.builtins}
    for v in vm.builtins.values():
        memo[id(v)] = v
    memo[id(vm.gate)] = new_gate
    frames, extra_copy = copy.deepcopy((vm.frames, extra), memo)
    child = PVM(vm.builtins, new_gate, vm.syscall_handler, vm.attr_guard)
    child.frames = frames
    child.icount = 0
    return child, extra_copy
