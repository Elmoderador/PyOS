# pong — contra el ordenador. ↑/↓ o W/S mueven tu pala; gana quien llegue a 7.
FW, FH = 60, 20
PAD = 4
WIN = 7


def play(scr):
    rng = Rng()
    while True:
        res = round_(scr, rng)
        if res is None:
            return 0
        me, cpu = res
        score = me * 100 - cpu * 10 if me > cpu else me * 10
        best = highscore("pong")
        highscore("pong", score)
        title = "¡GANASTE!" if me > cpu else "Gana la máquina"
        if not game_over(scr, title, score, best, "%d - %d" % (me, cpu)):
            return 0


def serve(rng, towards):
    return [FH / 2.0, FW / 2.0, rng.choice([-0.5, -0.35, 0.35, 0.5]), 1.0 * towards]


def round_(scr, rng):
    top = (scr.rows - FH - 2) // 2
    left = (scr.cols - FW - 2) // 2
    me = cpu = 0
    py = cy = FH // 2 - PAD // 2
    ball = serve(rng, rng.choice([-1, 1]))
    clock = Clock(25)
    wait = 20
    while True:
        for k in scr.keys():
            if k in ("q", "esc"):
                return None
            if k in ("up", "w"):
                py = max(0, py - 2)
            elif k in ("down", "s"):
                py = min(FH - PAD, py + 2)
        if wait:
            wait -= 1
        else:
            ball[0] += ball[2]
            ball[1] += ball[3]
            if ball[0] < 0:
                ball[0], ball[2] = -ball[0], -ball[2]
            if ball[0] > FH - 1:
                ball[0], ball[2] = 2 * (FH - 1) - ball[0], -ball[2]
            by = int(ball[0])
            if ball[1] <= 2 and ball[3] < 0:
                if py - 1 <= by <= py + PAD:
                    ball[3] = min(2.2, -ball[3] * 1.06)
                    ball[2] = (by - (py + PAD / 2.0)) * 0.3 + ball[2] * 0.5
                    ball[1] = 2
                elif ball[1] < 0:
                    cpu += 1
                    ball, wait = serve(rng, -1), 20
            elif ball[1] >= FW - 3 and ball[3] > 0:
                if cy - 1 <= by <= cy + PAD:
                    ball[3] = max(-2.2, -ball[3] * 1.06)
                    ball[2] = (by - (cy + PAD / 2.0)) * 0.3 + ball[2] * 0.5
                    ball[1] = FW - 3
                elif ball[1] > FW - 1:
                    me += 1
                    ball, wait = serve(rng, 1), 20
        # IA: sigue la pelota con retraso y algo de error
        if ball[3] > 0 and rng.chance(0.75):
            target = int(ball[0]) - PAD // 2 + rng.randint(-1, 1)
            if cy < target:
                cy += 1
            elif cy > target:
                cy -= 1
            cy = max(0, min(FH - PAD, cy))
        scr.clear()
        scr.box(top, left, FH + 2, FW + 2, True)
        scr.put(top, left + FW // 2 - 4, " %d  :  %d " % (me, cpu))
        for y in range(1, FH + 1, 2):
            scr.put(top + y, left + 1 + FW // 2, ":")
        for i in range(PAD):
            scr.put(top + 1 + py + i, left + 2, BLOCK)
            scr.put(top + 1 + cy + i, left + FW - 1, BLOCK)
        if 0 <= ball[1] < FW:
            scr.put(top + 1 + int(ball[0]), left + 1 + int(ball[1]), "O")
        scr.center(top + FH + 2, "↑/↓ o W/S · primero a %d · Q salir" % WIN)
        scr.present()
        if me >= WIN or cpu >= WIN:
            sleep_ms(600)
            return me, cpu
        clock.tick()


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
