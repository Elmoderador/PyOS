# Programas de prueba de la PVM: cada uno debe producir la misma salida que CPython.
# (sin f-strings con '=' ni sintaxis >3.6, para que corran en el Python de UEFI)
CASES = {}

CASES["basico"] = r'''
out = []
x = 3
y = x * 7 + 2 ** 3 - 10 // 3 % 4
out.append(y)
s = "hola" + " " + "mundo"
out.append(s.upper()[1:4])
out.append([i * i for i in range(6) if i % 2])
out.append({k: v for k, v in zip("abc", range(3))})
out.append({c for c in "abracadabra"} == set("abrcd"))
out.append(sum(i for i in range(10)))
a, b, *c = [1, 2, 3, 4, 5]
out.append((a, b, c))
d = {"x": 1}
d["y"] = d.get("x", 0) + 1
d["x"] += 10
out.append(sorted(d.items()))
out.append(1 < 2 < 3, )
out.append(1 < 3 < 2)
out.append(f"{x:>4}|{s!r}|{3.14159:.2f}")
out.append("%s-%d" % ("a", 5))
out.append(not None and 0 or "z")
lst = [5, 3, 9]
lst[1:2] = [7, 7]
del lst[0]
out.append(lst)
t = (1, 2)
out.append(t[::-1])
'''

CASES["funciones"] = r'''
out = []
def add(a, b=10, *rest, k=1, **kw):
    return a + b + sum(rest) + k + sum(kw.values())
out.append(add(1))
out.append(add(1, 2, 3, 4, k=5, z=6))
out.append(add(*[1, 2], **{"k": 0}))
def contador():
    n = 0
    def inc(step=1):
        nonlocal n
        n += step
        return n
    return inc
c = contador()
c(); c(); out.append(c(5))
def fact(n):
    return 1 if n <= 1 else n * fact(n - 1)
out.append(fact(20))
out.append(sorted(["bb", "a", "ccc"], key=lambda s: -len(s)))
out.append(list(map(lambda v: v * 2, [1, 2, 3])))
def deco(fn):
    def w(*a):
        return "<" + str(fn(*a)) + ">"
    return w
@deco
def doble(x):
    return x * 2
out.append(doble(21))
g = 5
def usa_global():
    global g
    g = g + 1
    return g
out.append(usa_global())
'''

CASES["generadores"] = r'''
out = []
def gen(n):
    for i in range(n):
        yield i * i
    yield "fin"
out.append([v for v in gen(4)])
out.append(list(gen(2)))
def lineas(texto):
    for l in texto.split("\n"):
        if l:
            yield l.strip()
for l in lineas("a\n b \n\nc"):
    out.append(l)
def delega():
    yield 0
    yield from gen(2)
out.append(list(delega()))
it = gen(3)
out.append(next(it))
out.append(next(it))
def fib():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b
r = []
for v in fib():
    if v > 50:
        break
    r.append(v)
out.append(r)
'''

CASES["excepciones"] = r'''
out = []
try:
    1 / 0
except ZeroDivisionError as e:
    out.append("zde")
try:
    [][3]
except (KeyError, IndexError):
    out.append("idx")
else:
    out.append("no")
def f():
    try:
        return "try"
    finally:
        out.append("finally-ret")
out.append(f())
def g():
    for i in range(5):
        try:
            if i == 2:
                break
            continue
        finally:
            out.append("fin%d" % i)
    return i
out.append(g())
try:
    try:
        raise ValueError("interno")
    except KeyError:
        out.append("mal")
except ValueError as e:
    out.append("relanzado:" + str(e))
try:
    try:
        raise OSError(2, "x")
    except OSError:
        raise
except OSError as e:
    out.append(e.args)
def h():
    try:
        raise RuntimeError("a")
    finally:
        out.append("limpieza")
try:
    h()
except RuntimeError:
    out.append("ok-h")
class MiError(Exception):
    pass
try:
    raise MiError("propio")
except Exception as e:
    out.append(type(e).__name__ if False else str(e))
n = 0
while n < 3:
    try:
        n += 1
        if n == 2:
            continue
        out.append(n)
    except Exception:
        pass
try:
    undefined_name
except NameError:
    out.append("nameerror")
'''

CASES["clases"] = r'''
out = []
class Punto:
    dim = 2
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def norma2(self):
        return self.x * self.x + self.y * self.y
    def __repr__(self):
        return "P(%d,%d)" % (self.x, self.y)
    def __eq__(self, o):
        return self.x == o.x and self.y == o.y
    def __hash__(self):
        return hash((self.x, self.y))
class Punto3(Punto):
    def __init__(self, x, y, z):
        Punto.__init__(self, x, y) if False else None
        self.x, self.y, self.z = x, y, z
    def norma2(self):
        return Punto.norma2(self) + self.z * self.z
p = Punto(3, 4)
out.append(p.norma2())
out.append(repr(p))
out.append(Punto3(1, 2, 2).norma2())
out.append(p == Punto(3, 4))
out.append(len({p, Punto(3, 4)}))
out.append(Punto.dim)
out.append(sorted([Punto(2, 0), Punto(1, 0)], key=lambda q: q.x))
out.append(isinstance(Punto3(0, 0, 0), Punto))
class Pila:
    def __init__(self):
        self._items = []
    def push(self, v):
        self._items.append(v)
        return self
    def __len__(self):
        return len(self._items)
    def __iter__(self):
        return iter(self._items)
s = Pila().push(1).push(2)
out.append(len(s))
out.append(list(s))
'''

CASES["with"] = r'''
out = []
class Ctx:
    def __init__(self, n):
        self.n = n
    def __enter__(self):
        out.append("enter%d" % self.n)
        return self.n
    def __exit__(self, t, v, tb):
        out.append("exit%d" % self.n)
        return t is KeyError
with Ctx(1) as a, Ctx(2) as b:
    out.append(a + b)
with Ctx(3):
    raise KeyError("x")
out.append("suprimida")
def f():
    with Ctx(4):
        return "ret"
out.append(f())
'''
