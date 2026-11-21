"""Compilador Python -> ISA de la PVM.

Funciona sobre el AST de Python 3.6 (Num/Str/NameConstant, Index/ExtSlice) y
de Python 3.8+ (Constant), para que el mismo kernel corra en el CPython de UEFI
y en el del host.

Diferencias semánticas documentadas respecto a CPython:
  - las expresiones generadoras se evalúan de forma ansiosa (como una lista);
  - las comprensiones no crean ámbito propio (su variable se ve fuera);
  - no hay async/await, import, match ni metaclases.
"""
import ast

from .isa import *  # noqa: F401,F403
from .isa import BINOP_INDEX, CMP_INDEX, UNARY_INDEX, Code


class CompileError(Exception):
    def __init__(self, filename, lineno, msg):
        Exception.__init__(self, "%s:%s: %s" % (filename, lineno, msg))
        self.filename, self.lineno, self.msg = filename, lineno, msg


def _const_value(node):
    """Devuelve (True, valor) si el nodo es una constante (3.6 o 3.8+)."""
    t = type(node).__name__
    if t == "Constant":
        return True, node.value
    if t == "Num":
        return True, node.n
    if t in ("Str", "Bytes"):
        return True, node.s
    if t == "NameConstant":
        return True, node.value
    if t == "Ellipsis":
        return True, Ellipsis
    return False, None


# ======================================================================= ámbitos
class Scope(object):
    def __init__(self, kind, name, parent):
        self.kind = kind            # module | function | class
        self.name = name
        self.parent = parent
        self.assigned = set()
        self.used = set()
        self.globals = set()
        self.nonlocals = set()
        self.params = []
        self.is_gen = False
        self.locals = set()
        self.cells = set()
        self.frees = set()
        self.children = []
        if parent is not None:
            parent.children.append(self)


class ScopeBuilder(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.scopes = {}
        self.cur = None

    def fail(self, node, msg):
        raise CompileError(self.filename, getattr(node, "lineno", "?"), msg)

    def build(self, tree):
        self.cur = Scope("module", "<module>", None)
        self.scopes[id(tree)] = self.cur
        for st in tree.body:
            self.visit(st)
        _resolve(self.cur, self.filename)
        return self.scopes

    # --- definiciones
    def _args(self, args):
        names = [a.arg for a in getattr(args, "posonlyargs", [])] + [a.arg for a in args.args]
        if args.vararg:
            names.append(args.vararg.arg)
        names += [a.arg for a in args.kwonlyargs]
        if args.kwarg:
            names.append(args.kwarg.arg)
        return names

    def _visit_args_defaults(self, args):
        for d in args.defaults:
            self.visit(d)
        for d in args.kw_defaults:
            if d is not None:
                self.visit(d)

    def _function(self, node, name, body, is_lambda=False):
        self._visit_args_defaults(node.args)
        parent = self.cur
        sc = Scope("function", name, parent)
        sc.params = self._args(node.args)
        sc.assigned.update(sc.params)
        self.scopes[id(node)] = sc
        self.cur = sc
        if is_lambda:
            self.visit(body)
        else:
            for st in body:
                self.visit(st)
        self.cur = parent

    def visit_FunctionDef(self, node):
        for d in node.decorator_list:
            self.visit(d)
        self.cur.assigned.add(node.name)
        self._function(node, node.name, node.body)

    def visit_AsyncFunctionDef(self, node):
        self.fail(node, "async no soportado")

    def visit_Lambda(self, node):
        self._function(node, "<lambda>", node.body, is_lambda=True)

    def visit_ClassDef(self, node):
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        if node.keywords:
            self.fail(node, "argumentos de clase (metaclass=...) no soportados")
        self.cur.assigned.add(node.name)
        parent = self.cur
        sc = Scope("class", node.name, parent)
        self.scopes[id(node)] = sc
        self.cur = sc
        for st in node.body:
            self.visit(st)
        self.cur = parent

    # --- nombres
    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.cur.assigned.add(node.id)
        else:
            self.cur.used.add(node.id)

    def visit_Global(self, node):
        self.cur.globals.update(node.names)

    def visit_Nonlocal(self, node):
        if self.cur.kind != "function":
            self.fail(node, "nonlocal fuera de función")
        self.cur.nonlocals.update(node.names)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.cur.assigned.add(node.name)
        self.generic_visit(node)

    def visit_Yield(self, node):
        if self.cur.kind != "function":
            self.fail(node, "yield fuera de función")
        self.cur.is_gen = True
        self.generic_visit(node)

    visit_YieldFrom = visit_Yield

    def visit_Import(self, node):
        self.fail(node, "'import' no existe en espacio de usuario de PyOS")

    visit_ImportFrom = visit_Import

    def visit_Await(self, node):
        self.fail(node, "await no soportado")

    def visit_NamedExpr(self, node):
        self.fail(node, "el operador := no está soportado")


def _resolve(scope, filename):
    if scope.kind == "function":
        scope.locals = (scope.assigned | set(scope.params)) - scope.globals - scope.nonlocals
    elif scope.kind == "class":
        scope.locals = scope.assigned - scope.globals
    for child in scope.children:
        _resolve(child, filename)
    if scope.kind == "module":
        _bind_frees(scope, filename)


def _bind_frees(scope, filename):
    for child in scope.children:
        _bind_frees(child, filename)
    if scope.kind == "module":
        return
    wanted = set(scope.nonlocals)
    if scope.kind == "function":
        wanted |= (scope.used - scope.locals - scope.globals)
    else:  # clase: lo no asignado en el cuerpo puede venir de una función externa
        wanted |= (scope.used - scope.assigned - scope.globals)
    for name in wanted:
        path = []
        s = scope.parent
        owner = None
        while s is not None and s.kind != "module":
            if s.kind == "function" and name in s.locals:
                owner = s
                break
            if s.kind == "function":
                path.append(s)
            s = s.parent
        if owner is None:
            if name in scope.nonlocals:
                raise CompileError(filename, "?", "no hay enlace para nonlocal '%s'" % name)
            continue
        owner.cells.add(name)
        scope.frees.add(name)
        for p in path:
            p.frees.add(name)


# ======================================================================= etiquetas
class Label(object):
    __slots__ = ("pos",)

    def __init__(self):
        self.pos = None


class _CB(object):
    """Bloque en tiempo de compilación (para break/continue)."""
    __slots__ = ("kind", "top", "brk", "rt_index")

    def __init__(self, kind, top=None, brk=None, rt_index=0):
        self.kind, self.top, self.brk, self.rt_index = kind, top, brk, rt_index


# ======================================================================= generador
class _Unit(object):
    def __init__(self, code, scope):
        self.code = code
        self.scope = scope
        self.varindex = {}
        self.cellindex = {}
        self.cblocks = []
        self.rt_depth = 0


class Compiler(object):
    def __init__(self, filename):
        self.filename = filename
        self.u = None
        self.line = 1

    # ------------------------------------------------------------------ util
    def fail(self, node, msg):
        raise CompileError(self.filename, getattr(node, "lineno", self.line), msg)

    def emit(self, op, arg=None):
        c = self.u.code
        c.ops.append(op)
        c.args.append(arg)
        c.lines.append(self.line)

    def mark(self, label):
        label.pos = len(self.u.code.ops)

    def const(self, value):
        self.emit(LOAD_CONST, value)

    def _setline(self, node):
        ln = getattr(node, "lineno", None)
        if ln:
            self.line = ln

    def _finish(self):
        c = self.u.code
        targets = set()
        for i, a in enumerate(c.args):
            if isinstance(a, Label):
                c.args[i] = a.pos
                targets.add(a.pos)
            elif isinstance(a, tuple) and a and isinstance(a[0], Label):
                c.args[i] = (a[0].pos,) + a[1:]
                targets.add(a[0].pos)
        c.simple = c.vararg is None and c.kwarg is None and not c.kwonly
        if OPTIMIZE:
            peephole(c, targets)
        return c

    # ------------------------------------------------------------------ unidades
    def compile_module(self, tree, scopes):
        self.scopes = scopes
        sc = scopes[id(tree)]
        code = Code("<module>", self.filename, "module")
        self.u = _Unit(code, sc)
        self._body(tree.body)
        self.const(None)
        self.emit(RETURN)
        return self._finish()

    def _new_unit(self, node, name, kind):
        sc = self.scopes[id(node)]
        code = Code(name, self.filename, kind)
        code.firstline = getattr(node, "lineno", 0)
        u = _Unit(code, sc)
        if kind == "function":
            params = sc.params
            locals_order = list(params) + sorted(sc.locals - set(params))
            u.varindex = dict((n, i) for i, n in enumerate(locals_order))
            code.varnames = locals_order
            code.nlocals = len(locals_order)
            code.cellvars = sorted(sc.cells)
            code.freevars = sorted(sc.frees)
            for i, n in enumerate(code.cellvars + code.freevars):
                u.cellindex[n] = i
            code.cell_of_arg = [(u.varindex[n], u.cellindex[n]) for n in code.cellvars if n in u.varindex]
            code.is_gen = sc.is_gen
        else:  # clase
            code.freevars = sorted(sc.frees)
            for i, n in enumerate(code.freevars):
                u.cellindex[n] = i
        return u

    def _closure_of(self, child_code):
        out = []
        for name in child_code.freevars:
            if name not in self.u.cellindex:
                self.fail(None, "error interno: celda '%s' no disponible" % name)
            out.append(self.u.cellindex[name])
        return tuple(out)

    # ------------------------------------------------------------------ nombres
    def load_name(self, name):
        u, sc = self.u, self.u.scope
        if sc.kind == "function":
            if name in u.cellindex:
                return self.emit(LOAD_DEREF, u.cellindex[name])
            if name in u.varindex:
                return self.emit(LOAD_FAST, u.varindex[name])
            return self.emit(LOAD_GLOBAL, name)
        if sc.kind == "class":
            if name in sc.assigned and name not in sc.globals:
                return self.emit(LOAD_CLASSNAME, name)
            if name in u.cellindex:
                return self.emit(LOAD_DEREF, u.cellindex[name])
        return self.emit(LOAD_GLOBAL, name)

    def store_name(self, name):
        u, sc = self.u, self.u.scope
        if sc.kind == "function":
            if name in u.cellindex:
                return self.emit(STORE_DEREF, u.cellindex[name])
            if name in u.varindex:
                return self.emit(STORE_FAST, u.varindex[name])
            return self.emit(STORE_GLOBAL, name)
        if sc.kind == "class" and name not in sc.globals:
            return self.emit(STORE_CLASSNAME, name)
        return self.emit(STORE_GLOBAL, name)

    def delete_name(self, name):
        u, sc = self.u, self.u.scope
        if sc.kind == "function" and name in u.varindex and name not in u.cellindex:
            return self.emit(DELETE_FAST, u.varindex[name])
        if sc.kind == "function" and name in u.cellindex:
            self.fail(None, "del de variable capturada no soportado")
        return self.emit(DELETE_GLOBAL, name)

    # ------------------------------------------------------------------ sentencias
    def _body(self, stmts):
        for st in stmts:
            self.stmt(st)

    def stmt(self, node):
        self._setline(node)
        m = getattr(self, "s_" + type(node).__name__, None)
        if m is None:
            self.fail(node, "sentencia no soportada: %s" % type(node).__name__)
        m(node)

    def s_Expr(self, node):
        self.expr(node.value)
        self.emit(POP)

    def s_Pass(self, node):
        pass

    def s_Global(self, node):
        pass

    s_Nonlocal = s_Global

    def s_Assign(self, node):
        self.expr(node.value)
        for i, t in enumerate(node.targets):
            if i < len(node.targets) - 1:
                self.emit(DUP)
            self.assign(t)

    def s_AnnAssign(self, node):
        if node.value is not None:
            self.expr(node.value)
            self.assign(node.target)

    def s_AugAssign(self, node):
        op = BINOP_INDEX[type(node.op).__name__]
        t = node.target
        if isinstance(t, ast.Name):
            self.load_name(t.id)
            self.expr(node.value)
            self.emit(INPLACE, op)
            self.store_name(t.id)
        elif isinstance(t, ast.Attribute):
            self.expr(t.value)
            self.emit(DUP)
            self.emit(LOAD_ATTR, t.attr)
            self.expr(node.value)
            self.emit(INPLACE, op)
            self.emit(ROT2)
            self.emit(STORE_ATTR, t.attr)
        elif isinstance(t, ast.Subscript):
            self.expr(t.value)
            self.subscript_index(t)
            self.emit(DUP2)
            self.emit(LOAD_SUBSCR)
            self.expr(node.value)
            self.emit(INPLACE, op)
            self.emit(ROT3)
            self.emit(STORE_SUBSCR)
        else:
            self.fail(node, "destino de asignación aumentada no válido")

    def assign(self, t):
        if isinstance(t, ast.Name):
            self.store_name(t.id)
        elif isinstance(t, ast.Attribute):
            self.expr(t.value)
            self.emit(STORE_ATTR, t.attr)
        elif isinstance(t, ast.Subscript):
            self.expr(t.value)
            self.subscript_index(t)
            self.emit(STORE_SUBSCR)
        elif isinstance(t, (ast.Tuple, ast.List)):
            stars = [i for i, e in enumerate(t.elts) if isinstance(e, ast.Starred)]
            if len(stars) > 1:
                self.fail(t, "más de un * en asignación")
            if stars:
                i = stars[0]
                self.emit(UNPACK_EX, (i, len(t.elts) - i - 1))
            else:
                self.emit(UNPACK, len(t.elts))
            for e in t.elts:
                self.assign(e.value if isinstance(e, ast.Starred) else e)
        else:
            self.fail(t, "destino de asignación no válido")

    def s_Delete(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name):
                self.delete_name(t.id)
            elif isinstance(t, ast.Attribute):
                self.expr(t.value)
                self.emit(DELETE_ATTR, t.attr)
            elif isinstance(t, ast.Subscript):
                self.expr(t.value)
                self.subscript_index(t)
                self.emit(DELETE_SUBSCR)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    self.s_Delete(ast.Delete(targets=[e]))
            else:
                self.fail(t, "del no soportado")

    def s_If(self, node):
        orelse, end = Label(), Label()
        self.expr(node.test)
        self.emit(POP_JUMP_IF_FALSE, orelse)
        self._body(node.body)
        if node.orelse:
            self.emit(JUMP, end)
        self.mark(orelse)
        self._body(node.orelse)
        self.mark(end)

    def _loop(self, node, is_for):
        u = self.u
        top, exit_, brk = Label(), Label(), Label()
        if is_for:
            self.expr(node.iter)
            self.emit(GET_ITER)
        self.emit(SETUP_LOOP, 1 if is_for else 0)
        rt_index = u.rt_depth
        u.rt_depth += 1
        u.cblocks.append(_CB("loop", top, brk, rt_index))
        self.mark(top)
        if is_for:
            self.emit(FOR_ITER, exit_)
            self.assign(node.target)
        else:
            self.expr(node.test)
            self.emit(POP_JUMP_IF_FALSE, exit_)
        self._body(node.body)
        self.emit(JUMP, top)
        self.mark(exit_)
        u.cblocks.pop()
        u.rt_depth -= 1
        self.emit(POP_BLOCK)
        self._body(node.orelse)
        self.mark(brk)

    def s_For(self, node):
        self._loop(node, True)

    def s_While(self, node):
        self._loop(node, False)

    def _find_loop(self, node):
        for cb in reversed(self.u.cblocks):
            if cb.kind == "loop":
                return cb
        self.fail(node, "break/continue fuera de un bucle")

    def s_Break(self, node):
        cb = self._find_loop(node)
        self.emit(UNWIND_JUMP, (cb.brk, cb.rt_index, False))

    def s_Continue(self, node):
        cb = self._find_loop(node)
        self.emit(UNWIND_JUMP, (cb.top, cb.rt_index + 1, True))

    def s_Return(self, node):
        if self.u.scope.kind != "function":
            self.fail(node, "return fuera de función")
        if node.value is None:
            self.const(None)
        else:
            self.expr(node.value)
        self.emit(RETURN)

    def s_Raise(self, node):
        if node.exc is None:
            self.emit(RAISE, 0)
            return
        self.expr(node.exc)
        if node.cause is not None:
            self.expr(node.cause)
            self.emit(RAISE, 2)
        else:
            self.emit(RAISE, 1)

    def s_Assert(self, node):
        end = Label()
        self.expr(node.test)
        self.emit(POP_JUMP_IF_TRUE, end)
        self.emit(LOAD_GLOBAL, "AssertionError")
        if node.msg is not None:
            self.expr(node.msg)
            self.emit(CALL, (1, ()))
        else:
            self.emit(CALL, (0, ()))
        self.emit(RAISE, 1)
        self.mark(end)

    def s_Try(self, node):
        u = self.u
        if node.finalbody:
            fin = Label()
            self.emit(SETUP_FINALLY, fin)
            u.rt_depth += 1
            u.cblocks.append(_CB("finally"))
            self._try_except(node)
            u.cblocks.pop()
            u.rt_depth -= 1
            self.emit(POP_BLOCK)
            self.const(None)        # marcador "sin evento"
            self.mark(fin)
            self._body(node.finalbody)
            self.emit(END_FINALLY)
        else:
            self._try_except(node)

    s_TryFinally = s_Try

    def _try_except(self, node):
        u = self.u
        if not node.handlers:
            self._body(node.body)
            self._body(node.orelse)
            return
        handler, end = Label(), Label()
        self.emit(SETUP_EXCEPT, handler)
        u.rt_depth += 1
        u.cblocks.append(_CB("except"))
        self._body(node.body)
        u.cblocks.pop()
        u.rt_depth -= 1
        self.emit(POP_BLOCK)
        self._body(node.orelse)
        self.emit(JUMP, end)
        self.mark(handler)
        # pila: [..., exc]; bloque de ejecución HANDLER activo
        u.rt_depth += 1
        u.cblocks.append(_CB("handler"))
        for h in node.handlers:
            self._setline(h)
            nxt = Label()
            if h.type is not None:
                self.emit(DUP)
                self.expr(h.type)
                self.emit(EXC_MATCH)
                self.emit(POP_JUMP_IF_FALSE, nxt)
            if h.name:
                self.store_name(h.name)
            else:
                self.emit(POP)
            self._body(h.body)
            self.emit(POP_EXCEPT)
            self.emit(JUMP, end)
            self.mark(nxt)
        self.emit(RAISE, 3)          # ningún except coincide: relanzar
        u.cblocks.pop()
        u.rt_depth -= 1
        self.mark(end)

    def s_With(self, node):
        u = self.u
        items = node.items
        exits = []
        for item in items:
            exit_ = Label()
            self.expr(item.context_expr)
            self.emit(SETUP_WITH, exit_)
            u.rt_depth += 1
            u.cblocks.append(_CB("with"))
            if item.optional_vars is not None:
                self.assign(item.optional_vars)
            else:
                self.emit(POP)
            exits.append(exit_)
        self._body(node.body)
        for exit_ in reversed(exits):
            u.cblocks.pop()
            u.rt_depth -= 1
            self.emit(POP_BLOCK)
            self.const(None)
            self.mark(exit_)
            self.emit(WITH_EXIT)

    def _function_code(self, node, name, body, is_lambda):
        saved, saved_line = self.u, self.line
        self.u = self._new_unit(node, name, "function")
        a = node.args
        c = self.u.code
        c.argcount = len(getattr(a, "posonlyargs", [])) + len(a.args)
        c.vararg = a.vararg.arg if a.vararg else None
        c.kwonly = [x.arg for x in a.kwonlyargs]
        c.kwarg = a.kwarg.arg if a.kwarg else None
        if is_lambda:
            self.expr(body)
            self.emit(RETURN)
        else:
            self._body(body)
            self.const(None)
            self.emit(RETURN)
        code = self._finish()
        self.u, self.line = saved, saved_line
        return code

    def _make_function(self, node, name, body, is_lambda=False):
        a = node.args
        for d in a.defaults:
            self.expr(d)
        self.emit(BUILD_TUPLE, len(a.defaults))
        kwd = [(k.arg, v) for k, v in zip(a.kwonlyargs, a.kw_defaults) if v is not None]
        for k, v in kwd:
            self.const(k)
            self.expr(v)
        self.emit(BUILD_MAP, len(kwd))
        code = self._function_code(node, name, body, is_lambda)
        self.emit(MAKE_FUNCTION, (code, self._closure_of(code)))

    def s_FunctionDef(self, node):
        for d in node.decorator_list:
            self.expr(d)
        self._make_function(node, node.name, node.body)
        for _ in node.decorator_list:
            self.emit(CALL, (1, ()))
        self.store_name(node.name)

    def s_ClassDef(self, node):
        for d in node.decorator_list:
            self.expr(d)
        for b in node.bases:
            self.expr(b)
        self.emit(BUILD_TUPLE, len(node.bases))
        saved, saved_line = self.u, self.line
        self.u = self._new_unit(node, node.name, "class")
        self._body(node.body)
        self.const(None)
        self.emit(RETURN)
        code = self._finish()
        self.u, self.line = saved, saved_line
        self.emit(MAKE_CLASS, (node.name, code, self._closure_of(code)))
        for _ in node.decorator_list:
            self.emit(CALL, (1, ()))
        self.store_name(node.name)

    # ------------------------------------------------------------------ expresiones
    def expr(self, node):
        self._setline(node)
        ok, v = _const_value(node)
        if ok:
            return self.const(v)
        m = getattr(self, "e_" + type(node).__name__, None)
        if m is None:
            self.fail(node, "expresión no soportada: %s" % type(node).__name__)
        m(node)

    def e_Name(self, node):
        self.load_name(node.id)

    def e_Attribute(self, node):
        self.expr(node.value)
        self.emit(LOAD_ATTR, node.attr)

    def subscript_index(self, node):
        sl = node.slice
        t = type(sl).__name__
        if t == "Index":            # Python 3.6-3.8
            sl = sl.value
            t = type(sl).__name__
        if t == "Slice":
            self._slice(sl)
        elif t == "ExtSlice":
            for d in sl.dims:
                if type(d).__name__ == "Slice":
                    self._slice(d)
                else:
                    self.expr(d.value if type(d).__name__ == "Index" else d)
            self.emit(BUILD_TUPLE, len(sl.dims))
        elif t == "Tuple" and any(type(e).__name__ == "Slice" for e in sl.elts):
            for e in sl.elts:
                if type(e).__name__ == "Slice":
                    self._slice(e)
                else:
                    self.expr(e)
            self.emit(BUILD_TUPLE, len(sl.elts))
        else:
            self.expr(sl)

    def _slice(self, sl):
        for part in (sl.lower, sl.upper):
            if part is None:
                self.const(None)
            else:
                self.expr(part)
        if sl.step is not None:
            self.expr(sl.step)
            self.emit(BUILD_SLICE, 3)
        else:
            self.emit(BUILD_SLICE, 2)

    def e_Subscript(self, node):
        self.expr(node.value)
        self.subscript_index(node)
        self.emit(LOAD_SUBSCR)

    def e_BinOp(self, node):
        self.expr(node.left)
        self.expr(node.right)
        self.emit(BINARY, BINOP_INDEX[type(node.op).__name__])

    def e_UnaryOp(self, node):
        self.expr(node.operand)
        self.emit(UNARY, UNARY_INDEX[type(node.op).__name__])

    def e_BoolOp(self, node):
        end = Label()
        op = JUMP_IF_FALSE_OR_POP if isinstance(node.op, ast.And) else JUMP_IF_TRUE_OR_POP
        for v in node.values[:-1]:
            self.expr(v)
            self.emit(op, end)
        self.expr(node.values[-1])
        self.mark(end)

    def e_Compare(self, node):
        self.expr(node.left)
        if len(node.ops) == 1:
            self.expr(node.comparators[0])
            self.emit(COMPARE, CMP_INDEX[type(node.ops[0]).__name__])
            return
        cleanup, end = Label(), Label()
        for i, (op, comp) in enumerate(zip(node.ops, node.comparators)):
            self.expr(comp)
            if i < len(node.ops) - 1:
                self.emit(DUP)
                self.emit(ROT3)
                self.emit(COMPARE, CMP_INDEX[type(op).__name__])
                self.emit(JUMP_IF_FALSE_OR_POP, cleanup)
            else:
                self.emit(COMPARE, CMP_INDEX[type(op).__name__])
        self.emit(JUMP, end)
        self.mark(cleanup)
        self.emit(ROT2)
        self.emit(POP)
        self.mark(end)

    def e_IfExp(self, node):
        orelse, end = Label(), Label()
        self.expr(node.test)
        self.emit(POP_JUMP_IF_FALSE, orelse)
        self.expr(node.body)
        self.emit(JUMP, end)
        self.mark(orelse)
        self.expr(node.orelse)
        self.mark(end)

    def _seq(self, elts, build_op):
        if any(isinstance(e, ast.Starred) for e in elts):
            self.emit(BUILD_LIST, 0)
            for e in elts:
                if isinstance(e, ast.Starred):
                    self.expr(e.value)
                    self.emit(LIST_EXTEND, 1)
                else:
                    self.expr(e)
                    self.emit(LIST_APPEND, 1)
            if build_op == BUILD_TUPLE:
                self.const(tuple)
                self.emit(ROT2)
                self.emit(CALL, (1, ()))
            elif build_op == BUILD_SET:
                self.const(set)
                self.emit(ROT2)
                self.emit(CALL, (1, ()))
            return
        for e in elts:
            self.expr(e)
        self.emit(build_op, len(elts))

    def e_Tuple(self, node):
        self._seq(node.elts, BUILD_TUPLE)

    def e_List(self, node):
        self._seq(node.elts, BUILD_LIST)

    def e_Set(self, node):
        self._seq(node.elts, BUILD_SET)

    def e_Dict(self, node):
        if any(k is None for k in node.keys):
            self.emit(BUILD_MAP, 0)
            for k, v in zip(node.keys, node.values):
                if k is None:
                    self.expr(v)
                    self.emit(DICT_UPDATE, 1)
                else:
                    self.expr(k)
                    self.expr(v)
                    self.emit(MAP_ADD, 1)
            return
        for k, v in zip(node.keys, node.values):
            self.expr(k)
            self.expr(v)
        self.emit(BUILD_MAP, len(node.keys))

    def e_Call(self, node):
        self.expr(node.func)
        star = any(isinstance(a, ast.Starred) for a in node.args) or \
            any(k.arg is None for k in node.keywords)
        if not star:
            for a in node.args:
                self.expr(a)
            names = []
            for k in node.keywords:
                self.expr(k.value)
                names.append(k.arg)
            self.emit(CALL, (len(node.args), tuple(names)))
            return
        self.emit(BUILD_LIST, 0)
        for a in node.args:
            if isinstance(a, ast.Starred):
                self.expr(a.value)
                self.emit(LIST_EXTEND, 1)
            else:
                self.expr(a)
                self.emit(LIST_APPEND, 1)
        self.emit(BUILD_MAP, 0)
        for k in node.keywords:
            if k.arg is None:
                self.expr(k.value)
                self.emit(DICT_UPDATE, 1)
            else:
                self.const(k.arg)
                self.expr(k.value)
                self.emit(MAP_ADD, 1)
        self.emit(CALL_EX)

    def e_Lambda(self, node):
        self._make_function(node, "<lambda>", node.body, is_lambda=True)

    def e_JoinedStr(self, node):
        for v in node.values:
            ok, c = _const_value(v)
            if ok:
                self.const(c)
            elif isinstance(v, ast.FormattedValue):
                self.expr(v.value)
                if v.format_spec is not None:
                    self.expr(v.format_spec)
                self.emit(FORMAT, (v.conversion, v.format_spec is not None))
            else:
                self.expr(v)
                self.emit(FORMAT, (-1, False))
        self.emit(BUILD_STRING, len(node.values))

    def e_FormattedValue(self, node):
        self.expr(node.value)
        if node.format_spec is not None:
            self.expr(node.format_spec)
        self.emit(FORMAT, (node.conversion, node.format_spec is not None))

    def e_Yield(self, node):
        if node.value is None:
            self.const(None)
        else:
            self.expr(node.value)
        self.emit(YIELD)

    def e_YieldFrom(self, node):
        top, end = Label(), Label()
        self.expr(node.value)
        self.emit(GET_ITER)
        self.mark(top)
        self.emit(FOR_ITER, end)
        self.emit(YIELD)
        self.emit(POP)
        self.emit(JUMP, top)
        self.mark(end)
        self.const(None)

    def e_Starred(self, node):
        self.fail(node, "* no permitido aquí")

    # --- comprensiones (ansiosas, sin ámbito propio)
    def _comprehension(self, node, kind):
        if kind == "dict":
            self.emit(BUILD_MAP, 0)
        elif kind == "set":
            self.emit(BUILD_SET, 0)
        else:
            self.emit(BUILD_LIST, 0)
        loops = []
        for gen in node.generators:
            top, exit_ = Label(), Label()
            self.expr(gen.iter)
            self.emit(GET_ITER)
            self.mark(top)
            self.emit(FOR_ITER, exit_)
            self.assign(gen.target)
            for cond in gen.ifs:
                self.expr(cond)
                self.emit(POP_JUMP_IF_FALSE, top)
            loops.append((top, exit_))
        depth = len(node.generators) + 1
        if kind == "dict":
            self.expr(node.key)
            self.expr(node.value)
            self.emit(MAP_ADD, depth)
        else:
            self.expr(node.elt)
            self.emit(SET_ADD if kind == "set" else LIST_APPEND, depth)
        for top, exit_ in reversed(loops):
            self.emit(JUMP, top)
            self.mark(exit_)

    def e_ListComp(self, node):
        self._comprehension(node, "list")

    def e_SetComp(self, node):
        self._comprehension(node, "set")

    def e_DictComp(self, node):
        self._comprehension(node, "dict")

    def e_GeneratorExp(self, node):
        self._comprehension(node, "list")
        self.emit(GET_ITER)


OPTIMIZE = True


def peephole(c, targets):
    """Superinstrucciones: fusiona pares frecuentes en una sola instrucción. La segunda
    posición queda como NOP (los índices no cambian) y el par nunca se fusiona si la
    segunda instrucción es destino de un salto."""
    from .vm import check_attr
    ops, args = c.ops, c.args
    n = len(ops)
    i = 0
    while i < n - 1:
        if (i + 1) in targets:
            i += 1
            continue
        a, b = ops[i], ops[i + 1]
        new = None
        if a == LOAD_FAST and b == LOAD_FAST:
            new = (LOAD_FAST2, (args[i], args[i + 1]))
        elif a == LOAD_FAST and b == LOAD_ATTR:
            name = args[i + 1]
            if not name.startswith("__"):
                try:
                    check_attr(name)
                    new = (LOAD_FAST_ATTR, (args[i], name))
                except AttributeError:
                    new = None
        elif a == LOAD_FAST and b == LOAD_CONST:
            new = (LOAD_FAST_CONST, (args[i], args[i + 1]))
        elif a == LOAD_CONST and b == BINARY:
            new = (BINARY_CONST, (args[i + 1], args[i]))
        elif a == COMPARE and b == POP_JUMP_IF_FALSE:
            new = (COMPARE_JUMP_FALSE, (args[i], args[i + 1]))
        elif a == STORE_FAST and b == LOAD_FAST:
            new = (STORE_LOAD_FAST, (args[i], args[i + 1]))
        elif a == INPLACE and b == STORE_FAST:
            new = (INPLACE_STORE_FAST, (args[i], args[i + 1]))
        if new is not None:
            ops[i], args[i] = new
            ops[i + 1], args[i + 1] = NOP, None
            i += 2
        else:
            i += 1


def compile_source(source, filename):
    """Fuente Python -> Code de módulo de la PVM."""
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as e:
        raise CompileError(filename, e.lineno, "error de sintaxis: %s" % e.msg)
    scopes = ScopeBuilder(filename).build(tree)
    return Compiler(filename).compile_module(tree, scopes)
