# breakout — rompe todos los ladrillos. ←/→ o A/D, Espacio saca, Q sale.
FW, FH = 56, 20
PW = 8
BRICK = 4                         # ancho de ladrillo
ROWS = 5


def play(scr):
    while True:
        res = round_(scr)
        if res is None:
            return 0
        score, level = res
        best = highscore("breakout")
        highscore("breakout", score)
        if not game_over(scr, "B R E A K O U T", score, best, "Nivel alcanzado: %d" % level):
            return 0


def new_wall():
    return [[1] * (FW // BRICK) for _ in range(ROWS)]


def round_(scr):
    top = (scr.rows - FH - 2) // 2
    left = (scr.cols - FW - 2) // 2
    wall = new_wall()
    px = FW // 2 - PW // 2
    lives, score, level = 3, 0, 1
    stuck = True
    ball = [FH - 2.0, FW / 2.0, -0.5, 0.7]
    clock = Clock(25)
    while True:
        for k in scr.keys():
            if k in ("q", "esc"):
                return None
            if k in ("left", "a"):
                px = max(0, px - 3)
            elif k in ("right", "d"):
                px = min(FW - PW, px + 3)
            elif k == "space" and stuck:
                stuck = False
        if stuck:
            ball[0], ball[1] = FH - 2.0, px + PW / 2.0
        else:
            sp = 1.0 + 0.15 * (level - 1)
            ny = ball[0] + ball[2] * sp
            nx = ball[1] + ball[3] * sp
            if nx < 0 or nx >= FW:
                ball[3] = -ball[3]
                nx = ball[1] + ball[3] * sp
            if ny < 0:
                ball[2] = -ball[2]
                ny = ball[0] + ball[2] * sp
            row, col = int(ny) - 2, int(nx) // BRICK
            if 0 <= row < ROWS and 0 <= col < len(wall[0]) and wall[row][col]:
                wall[row][col] = 0
                score += (ROWS - row) * 10 * level
                ball[2] = -ball[2]
                ny = ball[0]
            if ny >= FH - 1 and ball[2] > 0:
                if px - 1 <= nx <= px + PW:
                    hit = (nx - (px + PW / 2.0)) / (PW / 2.0)
                    ball[3] = max(-1.2, min(1.2, hit * 1.1))
                    ball[2] = -abs(ball[2])
                    ny = FH - 2
                elif ny >= FH:
                    lives -= 1
                    stuck = True
                    if lives == 0:
                        return score, level
                    ball[2] = -0.5
            ball[0], ball[1] = ny, nx
            if not any(any(r) for r in wall):
                level += 1
                wall = new_wall()
                stuck = True
        scr.clear()
        scr.box(top, left, FH + 2, FW + 2, True)
        scr.put(top, left + 2, " Puntos %d " % score)
        scr.put(top, left + FW - 16, " Vidas %s " % ("O" * lives))
        for r in range(ROWS):
            line = "".join(((BLOCK * (BRICK - 1)) + " ") if b else " " * BRICK for b in wall[r])
            scr.put(top + 3 + r, left + 1, line if r % 2 == 0 else line.replace(BLOCK, SHADE))
        scr.put(top + FH, left + 1 + px, "=" * PW)
        scr.put(top + 1 + int(ball[0]), left + 1 + int(ball[1]), "o")
        if stuck:
            scr.center(top + FH // 2 + 3, "Nivel %d — Espacio para sacar" % level)
        scr.center(top + FH + 2, "←/→ o A/D · Espacio sacar · Q salir")
        scr.present()
        clock.tick()


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
