# minas — buscaminas. Flechas/WASD mover, Espacio/Intro destapar, F bandera, Q sale.
W, HH, MINES = 16, 12, 28


def play(scr):
    rng = Rng()
    while True:
        res = round_(scr, rng)
        if res is None:
            return 0
        won, secs = res
        score = max(0, 1000 - secs * 5) if won else 0
        best = highscore("minas")
        highscore("minas", score)
        title = "¡DESPEJADO!" if won else "¡BOOM!"
        if not game_over(scr, title, score, best, "Tiempo: %d s" % secs):
            return 0


def neighbours(r, c):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and 0 <= r + dr < HH and 0 <= c + dc < W:
                yield r + dr, c + dc


def round_(scr, rng):
    mines = set()
    counts = None
    opened = set()
    flags = set()
    cr, cc = HH // 2, W // 2
    t0 = None
    while True:
        secs = 0 if t0 is None else (uptime_ms() - t0) // 1000
        draw(scr, mines, counts, opened, flags, cr, cc, secs, False)
        scr.present()
        ks = scr.keys()
        if not ks:
            sleep_ms(40)
            continue
        for k in ks:
            if k in ("q", "esc"):
                return None
            if k in ("up", "w"):
                cr = (cr - 1) % HH
            elif k in ("down", "s"):
                cr = (cr + 1) % HH
            elif k in ("left", "a"):
                cc = (cc - 1) % W
            elif k in ("right", "d"):
                cc = (cc + 1) % W
            elif k == "f" and (cr, cc) not in opened:
                if (cr, cc) in flags:
                    flags.discard((cr, cc))
                else:
                    flags.add((cr, cc))
            elif k in ("space", "enter") and (cr, cc) not in flags:
                if counts is None:                       # la primera jugada nunca es mina
                    safe = set(neighbours(cr, cc)) | {(cr, cc)}
                    while len(mines) < MINES:
                        p = (rng.randint(0, HH - 1), rng.randint(0, W - 1))
                        if p not in safe:
                            mines.add(p)
                    counts = {}
                    for r in range(HH):
                        for c in range(W):
                            counts[(r, c)] = sum(1 for p in neighbours(r, c) if p in mines)
                    t0 = uptime_ms()
                if (cr, cc) in mines:
                    secs = (uptime_ms() - t0) // 1000
                    draw(scr, mines, counts, opened, flags, cr, cc, secs, True)
                    scr.present()
                    sleep_ms(1200)
                    return False, secs
                flood(cr, cc, counts, opened, flags)
                if len(opened) == W * HH - MINES:
                    secs = (uptime_ms() - t0) // 1000
                    draw(scr, mines, counts, opened, flags, cr, cc, secs, True)
                    scr.present()
                    sleep_ms(900)
                    return True, secs


def flood(r, c, counts, opened, flags):
    stack = [(r, c)]
    while stack:
        p = stack.pop()
        if p in opened or p in flags:
            continue
        opened.add(p)
        if counts[p] == 0:
            for q in neighbours(p[0], p[1]):
                if q not in opened:
                    stack.append(q)


def draw(scr, mines, counts, opened, flags, cr, cc, secs, reveal):
    scr.clear()
    top = (scr.rows - HH * 1 - 2) // 2
    left = (scr.cols - W * 3 - 2) // 2
    scr.box(top, left, HH + 2, W * 3 + 2, True)
    scr.put(top, left + 2, " Minas %d " % (MINES - len(flags)))
    scr.put(top, left + W * 3 - 10, " %3d s " % secs)
    for r in range(HH):
        cells = []
        for c in range(W):
            p = (r, c)
            if reveal and p in mines:
                ch = "*"
            elif p in flags:
                ch = "F"
            elif p in opened:
                n = counts[p]
                ch = str(n) if n else " "
            else:
                ch = SHADE
            if p == (cr, cc):
                cells.append("[" + ch + "]")
            else:
                cells.append(" " + ch + " ")
        scr.put(top + 1 + r, left + 1, "".join(cells))
    scr.center(top + HH + 2, "Flechas mover · Espacio destapar · F bandera · Q salir")


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
