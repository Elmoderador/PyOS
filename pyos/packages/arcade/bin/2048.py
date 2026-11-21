# 2048 — junta fichas iguales hasta llegar a 2048. Flechas/WASD, U deshacer, Q sale.
N = 4
CW, CH = 8, 3                     # tamaño de cada casilla en celdas de texto
MOVES = {"up": "up", "w": "up", "down": "down", "s": "down",
         "left": "left", "a": "left", "right": "right", "d": "right"}


def slide(line):
    vals = [v for v in line if v]
    out = []
    gained = 0
    i = 0
    while i < len(vals):
        if i + 1 < len(vals) and vals[i] == vals[i + 1]:
            out.append(vals[i] * 2)
            gained += vals[i] * 2
            i += 2
        else:
            out.append(vals[i])
            i += 1
    return out + [0] * (N - len(out)), gained


def move(b, d):
    nb = [row[:] for row in b]
    total = 0
    for i in range(N):
        if d in ("left", "right"):
            line = nb[i][:] if d == "left" else nb[i][::-1]
        else:
            line = [nb[r][i] for r in range(N)]
            if d == "down":
                line = line[::-1]
        res, g = slide(line)
        total += g
        if d in ("right", "down"):
            res = res[::-1]
        if d in ("left", "right"):
            nb[i] = res
        else:
            for r in range(N):
                nb[r][i] = res[r]
    return nb, total


def spawn(b, rng):
    empty = [(r, c) for r in range(N) for c in range(N) if not b[r][c]]
    if empty:
        r, c = rng.choice(empty)
        b[r][c] = 4 if rng.chance(0.1) else 2


def stuck(b):
    for d in ("up", "down", "left", "right"):
        if move(b, d)[0] != b:
            return False
    return True


def play(scr):
    rng = Rng()
    while True:
        res = round_(scr, rng)
        if res is None:
            return 0
        score, top_tile = res
        best = highscore("2048")
        highscore("2048", score)
        if not game_over(scr, "2 0 4 8", score, best, "Ficha máxima: %d" % top_tile):
            return 0


def round_(scr, rng):
    b = [[0] * N for _ in range(N)]
    spawn(b, rng)
    spawn(b, rng)
    score = 0
    undo = None
    won = False
    msg = ""
    while True:
        draw(scr, b, score, msg)
        scr.present()
        k = scr.wait_key()
        msg = ""
        if k in ("q", "esc"):
            return None
        if k == "u" and undo:
            b, score = undo
            undo = None
            continue
        if k not in MOVES:
            continue
        nb, g = move(b, MOVES[k])
        if nb == b:
            continue
        undo = ([row[:] for row in b], score)
        b, score = nb, score + g
        spawn(b, rng)
        top_tile = max(max(row) for row in b)
        if top_tile >= 2048 and not won:
            won = True
            msg = "¡2048! Sigue si quieres"
        if stuck(b):
            draw(scr, b, score, "Sin movimientos")
            scr.present()
            sleep_ms(900)
            return score, top_tile


def draw(scr, b, score, msg):
    scr.clear()
    w, h = N * (CW + 1) + 1, N * (CH + 1) + 1
    top = (scr.rows - h) // 2
    left = (scr.cols - w) // 2
    scr.center(top - 2, "2 0 4 8      Puntos: %d" % score)
    for r in range(N + 1):
        y = top + r * (CH + 1)
        scr.put(y, left, ("+" + "-" * CW) * N + "+")
    for r in range(N):
        for c in range(N):
            v = b[r][c]
            y = top + 1 + r * (CH + 1)
            x = left + 1 + c * (CW + 1)
            for i in range(CH):
                scr.put(y + i, x - 1, "|")
            scr.put(y, left + w - 1, "|")
            scr.put(y + 1, left + w - 1, "|")
            scr.put(y + 2, left + w - 1, "|")
            if v:
                fill = SHADE if v >= 128 else " "
                scr.put(y, x, fill * CW)
                scr.put(y + 2, x, fill * CW)
                txt = str(v)
                scr.put(y + 1, x, (fill * ((CW - len(txt)) // 2) + txt).ljust(CW, fill))
    scr.center(top + h + 1, msg if msg else "Flechas/WASD · U deshacer · Q salir")


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
