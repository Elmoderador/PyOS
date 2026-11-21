# snake — come, crece y no te muerdas. Flechas/WASD, P pausa, Q sale.
W, HH = 24, 18                 # celdas del tablero (cada celda = 2 columnas)
DIRS = {"up": (-1, 0), "w": (-1, 0), "down": (1, 0), "s": (1, 0),
        "left": (0, -1), "a": (0, -1), "right": (0, 1), "d": (0, 1)}


def play(scr):
    rng = Rng()
    while True:
        score = round_(scr, rng)
        if score is None:
            return 0
        best = highscore("snake")
        highscore("snake", score)
        if not game_over(scr, "S N A K E", score, best):
            return 0


def round_(scr, rng):
    top = (scr.rows - HH - 2) // 2
    left = (scr.cols - W * 2 - 2) // 2
    snake = [(HH // 2, W // 2 - i) for i in range(4)]
    body = set(snake)
    d = (0, 1)
    queue = []
    food = place(rng, body)
    score = 0
    fps = 7
    clock = Clock(fps)
    paused = False
    while True:
        for k in scr.keys():
            if k in ("q", "esc"):
                return None
            if k == "p":
                paused = not paused
            elif k in DIRS and len(queue) < 3:
                queue.append(DIRS[k])
        if not paused:
            while queue:
                nd = queue.pop(0)
                if nd[0] != -d[0] or nd[1] != -d[1]:
                    if nd != d:
                        d = nd
                        break
            hr, hc = snake[0]
            nr, nc = hr + d[0], hc + d[1]
            tail = snake[-1]
            if nr < 0 or nr >= HH or nc < 0 or nc >= W or ((nr, nc) in body and (nr, nc) != tail):
                draw(scr, top, left, snake, food, score, "¡Chocaste!")
                scr.present()
                sleep_ms(700)
                return score
            snake.insert(0, (nr, nc))
            body.add((nr, nc))
            if (nr, nc) == food:
                score += 10
                if len(snake) >= W * HH:
                    return score
                food = place(rng, body)
                if score % 50 == 0 and fps < 16:
                    fps += 1
                    clock = Clock(fps)
            else:
                t = snake.pop()
                if t != (nr, nc):
                    body.discard(t)
        draw(scr, top, left, snake, food, score, "PAUSA (P)" if paused else "")
        scr.present()
        clock.tick()


def place(rng, body):
    while True:
        p = (rng.randint(0, HH - 1), rng.randint(0, W - 1))
        if p not in body:
            return p


def draw(scr, top, left, snake, food, score, msg):
    scr.clear()
    scr.box(top, left, HH + 2, W * 2 + 2, True)
    scr.put(top, left + 3, " SNAKE ")
    scr.put(top, left + W * 2 - 14, " %5d pts " % score)
    for (r, c) in snake[1:]:
        scr.put(top + 1 + r, left + 1 + c * 2, BLOCK + BLOCK)
    hr, hc = snake[0]
    scr.put(top + 1 + hr, left + 1 + hc * 2, "[]")
    scr.put(top + 1 + food[0], left + 1 + food[1] * 2, "<>")
    scr.center(top + HH + 2, msg if msg else "Flechas/WASD mover · P pausa · Q salir")


def main(argv):
    include("/lib/tui.py")
    return run_game(play)
