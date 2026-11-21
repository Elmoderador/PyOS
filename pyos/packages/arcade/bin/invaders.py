# invaders — defiende la Tierra. ←/→ o A/D mover, Espacio disparar, Q sale.
FW, FH = 60, 22
COLS, ROWS = 9, 4
SPRITES = [("/^\\", "\\^/"), ("<O>", ">O<"), ("{#}", "}#{"), ("(o)", ")o(")]


def play(scr):
    rng = Rng()
    while True:
        res = round_(scr, rng)
        if res is None:
            return 0
        score, wave = res
        best = highscore("invaders")
        highscore("invaders", score)
        if not game_over(scr, "I N V A D E R S", score, best, "Oleada: %d" % wave):
            return 0


def round_(scr, rng):
    top = (scr.rows - FH - 2) // 2
    left = (scr.cols - FW - 2) // 2
    score, lives, wave = 0, 3, 1
    while True:
        res = wave_(scr, rng, top, left, score, lives, wave)
        if res is None:
            return None
        score, lives, cleared = res
        if not cleared:
            return score, wave
        wave += 1


def wave_(scr, rng, top, left, score, lives, wave):
    aliens = {}
    for r in range(ROWS):
        for c in range(COLS):
            aliens[(r, c)] = True
    ox, oy, dx = 2, 1 + min(wave - 1, 4), 1
    px = FW // 2
    shots = []                    # disparos propios [y, x]
    bombs = []                    # bombas [y, x]
    shields = set()
    for s in range(4):
        bx = 6 + s * 14
        for y in range(2):
            for x in range(5):
                shields.add((FH - 5 + y, bx + x))
    clock = Clock(20)
    t = 0
    step_every = max(2, 12 - wave)
    cooldown = 0
    while True:
        for k in scr.keys():
            if k in ("q", "esc"):
                return None
            if k in ("left", "a"):
                px = max(1, px - 2)
            elif k in ("right", "d"):
                px = min(FW - 2, px + 2)
            elif k in ("space", "w", "up") and cooldown == 0 and len(shots) < 2:
                shots.append([FH - 2, px])
                cooldown = 4
        cooldown = max(0, cooldown - 1)
        t += 1
        alive = len(aliens)
        if alive == 0:
            return score, lives, True
        if t % max(1, step_every * alive // (ROWS * COLS) + 1) == 0:
            cs = [c for (r, c) in aliens]
            minx = ox + min(cs) * 6
            maxx = ox + max(cs) * 6 + 2
            if (dx > 0 and maxx + dx >= FW) or (dx < 0 and minx + dx < 0):
                dx = -dx
                oy += 1
            else:
                ox += dx
        for s in shots:
            s[0] -= 1
        for b in bombs:
            if t % 2 == 0:
                b[0] += 1
        if rng.chance(0.04 + 0.01 * wave):
            col = {}
            for (r, c) in aliens:
                if r >= col.get(c, -1):
                    col[c] = r
            c = rng.choice(list(col))
            bombs.append([oy + col[c] * 2 + 1, ox + c * 6 + 1])
        for s in shots[:]:
            hit = None
            for (r, c) in aliens:
                ay, ax = oy + r * 2, ox + c * 6
                if s[0] == ay and ax <= s[1] <= ax + 2:
                    hit = (r, c)
                    break
            if hit:
                del aliens[hit]
                score += (ROWS - hit[0]) * 10
                shots.remove(s)
            elif (s[0], s[1]) in shields:
                shields.discard((s[0], s[1]))
                shots.remove(s)
            elif s[0] < 0:
                shots.remove(s)
        for b in bombs[:]:
            if (b[0], b[1]) in shields:
                shields.discard((b[0], b[1]))
                bombs.remove(b)
            elif b[0] >= FH - 1:
                if abs(b[1] - px) <= 1:
                    lives -= 1
                    bombs = []
                    flash(scr, top, left)
                    if lives == 0:
                        return score, 0, False
                    break
                bombs.remove(b)
        lowest = max(r for (r, c) in aliens)
        if oy + lowest * 2 >= FH - 2:
            return score, 0, False
        scr.clear()
        scr.box(top, left, FH + 2, FW + 2, True)
        scr.put(top, left + 2, " Puntos %d " % score)
        scr.put(top, left + FW // 2 - 5, " Oleada %d " % wave)
        scr.put(top, left + FW - 12, " Vidas %d " % lives)
        frame = (t // 6) % 2
        for (r, c) in aliens:
            spr = SPRITES[r][frame]
            scr.put(top + 1 + oy + r * 2, left + 1 + ox + c * 6, spr)
        for (y, x) in shields:
            scr.put(top + 1 + y, left + 1 + x, SHADE)
        for s in shots:
            scr.put(top + 1 + s[0], left + 1 + s[1], "|")
        for b in bombs:
            scr.put(top + 1 + b[0], left + 1 + b[1], "*")
        scr.put(top + FH, left + px, "/" + UP + "\\")
        scr.center(top + FH + 2, "←/→ mover · Espacio disparar · Q salir")
        scr.present()
        clock.tick()


def flash(scr, top, left):
    scr.center(top + FH // 2, "  ¡TE HAN DADO!  ")
    scr.present()
    sleep_ms(800)


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
