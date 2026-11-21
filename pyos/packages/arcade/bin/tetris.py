# tetris — ←/→ mover, ↑ girar, ↓ bajar, Espacio caída, P pausa, Q sale.
W, HH = 10, 20
PIECES = [
    [(0, 0), (0, 1), (0, 2), (0, 3)],          # I
    [(0, 0), (0, 1), (1, 0), (1, 1)],          # O
    [(0, 1), (1, 0), (1, 1), (1, 2)],          # T
    [(0, 1), (0, 2), (1, 0), (1, 1)],          # S
    [(0, 0), (0, 1), (1, 1), (1, 2)],          # Z
    [(0, 0), (1, 0), (1, 1), (1, 2)],          # J
    [(0, 2), (1, 0), (1, 1), (1, 2)],          # L
]
LINE_POINTS = [0, 100, 300, 500, 800]


def rotate(cells):
    rs = [(c, -r) for r, c in cells]
    mr = min(r for r, c in rs)
    mc = min(c for r, c in rs)
    return [(r - mr, c - mc) for r, c in rs]


def fits(board, cells, r, c):
    for dr, dc in cells:
        y, x = r + dr, c + dc
        if x < 0 or x >= W or y >= HH:
            return False
        if y >= 0 and board[y][x]:
            return False
    return True


def play(scr):
    rng = Rng()
    while True:
        res = round_(scr, rng)
        if res is None:
            return 0
        score, lines = res
        best = highscore("tetris")
        highscore("tetris", score)
        if not game_over(scr, "T E T R I S", score, best, "Líneas: %d" % lines):
            return 0


def round_(scr, rng):
    board = [[0] * W for _ in range(HH)]
    top = (scr.rows - HH - 2) // 2
    left = (scr.cols - W * 2 - 2) // 2 - 8
    bag = []

    def nextp():
        if not bag:
            bag.extend(range(7))
            for i in range(6, 0, -1):
                j = rng.randint(0, i)
                bag[i], bag[j] = bag[j], bag[i]
        return PIECES[bag.pop()]
    cur = nextp()
    nxt = nextp()
    r, c = -1, W // 2 - 2
    score = lines = 0
    level = 1
    clock = Clock(20)
    t = 0
    paused = False
    while True:
        drop = False
        for k in scr.keys():
            if k in ("q", "esc"):
                return None
            if k == "p":
                paused = not paused
            if paused:
                continue
            if k in ("left", "a") and fits(board, cur, r, c - 1):
                c -= 1
            elif k in ("right", "d") and fits(board, cur, r, c + 1):
                c += 1
            elif k in ("up", "w", "x"):
                rot = rotate(cur)
                for kick in (0, -1, 1, -2, 2):
                    if fits(board, rot, r, c + kick):
                        cur, c = rot, c + kick
                        break
            elif k in ("down", "s"):
                if fits(board, cur, r + 1, c):
                    r += 1
                    score += 1
            elif k == "space":
                while fits(board, cur, r + 1, c):
                    r += 1
                    score += 2
                drop = True
        if not paused:
            t += 1
            if drop or t >= max(2, 21 - level * 2):
                t = 0
                if fits(board, cur, r + 1, c):
                    r += 1
                else:
                    for dr, dc in cur:
                        if r + dr < 0:
                            draw(scr, board, cur, r, c, nxt, top, left, score, lines, level, "FIN")
                            scr.present()
                            sleep_ms(700)
                            return score, lines
                        board[r + dr][c + dc] = 1
                    full = [y for y in range(HH) if all(board[y])]
                    for y in full:
                        del board[y]
                        board.insert(0, [0] * W)
                    lines += len(full)
                    score += LINE_POINTS[len(full)] * level
                    level = 1 + lines // 10
                    cur, nxt = nxt, nextp()
                    r, c = -1, W // 2 - 2
                    if not fits(board, cur, r, c):
                        return score, lines
        draw(scr, board, cur, r, c, nxt, top, left, score, lines, level, "PAUSA" if paused else "")
        scr.present()
        clock.tick()


def draw(scr, board, cur, r, c, nxt, top, left, score, lines, level, msg):
    scr.clear()
    scr.box(top, left, HH + 2, W * 2 + 2, True)
    ghost = r
    while fits(board, cur, ghost + 1, c):
        ghost += 1
    for y in range(HH):
        row = board[y]
        scr.put(top + 1 + y, left + 1, "".join((BLOCK + BLOCK) if v else " ." for v in row))
    for dr, dc in cur:
        if ghost + dr >= 0:
            scr.put(top + 1 + ghost + dr, left + 1 + (c + dc) * 2, SHADE + SHADE)
    for dr, dc in cur:
        if r + dr >= 0:
            scr.put(top + 1 + r + dr, left + 1 + (c + dc) * 2, BLOCK + BLOCK)
    px = left + W * 2 + 5
    scr.put(top, px, "TETRIS")
    scr.put(top + 2, px, "Puntos  %d" % score)
    scr.put(top + 3, px, "Líneas  %d" % lines)
    scr.put(top + 4, px, "Nivel   %d" % level)
    scr.put(top + 6, px, "Siguiente:")
    scr.box(top + 7, px, 4, 10)
    for dr, dc in nxt:
        scr.put(top + 8 + dr, px + 1 + dc * 2, BLOCK + BLOCK)
    for i, line in enumerate(["←→  mover", "↑   girar", "↓   bajar", "Esp caer", "P   pausa", "Q   salir"]):
        scr.put(top + 13 + i, px, line)
    if msg:
        scr.put(top + HH // 2, left + W - len(msg) // 2 + 1, msg)


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
