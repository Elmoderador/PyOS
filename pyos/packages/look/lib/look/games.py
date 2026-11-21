# /lib/look/games.py — juegos gráficos de PyOS LOOK: Buscaminas y Serpiente, y el centro de juegos.
# Solo se repintan las casillas que cambian (wm.damage de su rectángulo): en UEFI cada
# rectángulo de píxeles es trabajo real, así que no se redibuja el tablero entero.


class LRng:
    def __init__(self):
        try:
            fd = open("/dev/random")
            b = read(fd, 4)
            close(fd)
            self.s = (b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24) or 0x2545F491
        except OSError:
            self.s = (uptime_ms() * 2654435761) & 0xFFFFFFFF or 1

    def next(self):
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x
        return x

    def below(self, n):
        return self.next() % n


def best_get(name):
    try:
        return int(read_file("/var/games/" + name).decode().strip())
    except (OSError, ValueError):
        return None


def best_put(name, value):
    try:
        if not exists("/var/games"):
            mkdir("/var/games")
        write_file("/var/games/" + name, ("%d\n" % value).encode())
        sync()
    except OSError:
        pass


MINE_LEVELS = [("Fácil", 9, 9, 10), ("Medio", 16, 16, 40), ("Difícil", 30, 16, 99)]
NUM_COLORS = [None, 0x2563EB, 0x16A34A, 0xDC2626, 0x1E3A8A, 0x7F1D1D, 0x0E7490, 0x111827, 0x6B7280]
FLAG = (["..r....", "..rrr..", "..rrrr.", "..r....", "..r....", ".kkkk..", "kkkkkk."],
        {"r": 0xDC2626, "k": 0x111827})
MINE = (["...k...", ".kkkkk.", ".kwkkk.", "kkkkkkk", ".kkkkk.", ".kkkkk.", "...k..."],
        {"k": 0x111827, "w": 0xFFFFFF})


class Minesweeper(Window):
    icon = "mines"
    resizable = False
    CELL = 24
    TOP = 48

    def __init__(self, level=1):
        self.level = level
        name, cols, rows, mines = MINE_LEVELS[level]
        Window.__init__(self, "Buscaminas", cols * self.CELL + 2 + 16, rows * self.CELL + self.TOP + 8 + TITLE_H + 1)
        self.rng = LRng()
        for i, lv in enumerate(MINE_LEVELS):
            self.add_button(8 + i * 76, 10, 72, 28, lv[0], self._lvl(i), i == level)
        self.new_game()

    def _lvl(self, i):
        def f():
            if self.wm is None:
                return
            wm = self.wm
            x, y = self.x, self.y
            self.close()
            wm.add(Minesweeper(i), x, y)
        return f

    def new_game(self):
        name, self.cols, self.rows, self.mines = MINE_LEVELS[self.level]
        n = self.cols * self.rows
        self.mine = [False] * n
        self.state = [0] * n          # 0 tapada, 1 destapada, 2 bandera
        self.count = [0] * n
        self.placed = False
        self.over = None              # None, "win", "lose"
        self.boom = -1
        self.flags = 0
        self.left = n - self.mines
        self.t0 = None
        self.t_end = None
        self.shown_t = -1
        self.redraw()

    def place(self, safe):
        sx, sy = safe % self.cols, safe // self.cols
        free = [i for i in range(self.cols * self.rows)
                if abs(i % self.cols - sx) > 1 or abs(i // self.cols - sy) > 1]
        for k in range(self.mines):
            j = k + self.rng.below(len(free) - k)
            free[k], free[j] = free[j], free[k]
            self.mine[free[k]] = True
        for i in range(self.cols * self.rows):
            self.count[i] = sum(1 for j in self.neigh(i) if self.mine[j])
        self.placed = True
        self.t0 = uptime_ms()

    def neigh(self, i):
        x, y = i % self.cols, i // self.cols
        out = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.cols and 0 <= ny < self.rows:
                        out.append(ny * self.cols + nx)
        return out

    def elapsed(self):
        if self.t0 is None:
            return 0
        end = self.t_end if self.t_end is not None else uptime_ms()
        return min(999, (end - self.t0) // 1000)

    # ---------------------------------------------------------- jugadas
    def reveal(self, i):
        if self.state[i] != 0:
            return
        if not self.placed:
            self.place(i)
        if self.mine[i]:
            self.lose(i)
            return
        stack = [i]
        while stack:
            j = stack.pop()
            if self.state[j] != 0:
                continue
            self.state[j] = 1
            self.left -= 1
            self.damage_cell(j)
            if self.count[j] == 0:
                stack.extend(k for k in self.neigh(j) if self.state[k] == 0)
        if self.left == 0:
            self.win()

    def chord(self, i):
        if self.state[i] != 1 or not self.count[i]:
            return
        nb = self.neigh(i)
        if sum(1 for j in nb if self.state[j] == 2) == self.count[i]:
            for j in nb:
                if self.over is None:
                    self.reveal(j)

    def flag(self, i):
        if self.state[i] == 1:
            return
        self.state[i] = 0 if self.state[i] == 2 else 2
        self.flags += 1 if self.state[i] == 2 else -1
        self.damage_cell(i)
        self.damage_header()

    def lose(self, i):
        self.over = "lose"
        self.boom = i
        self.t_end = uptime_ms()
        self.redraw()

    def win(self):
        self.over = "win"
        self.t_end = uptime_ms()
        for j in range(len(self.mine)):
            if self.mine[j]:
                self.state[j] = 2
        self.flags = self.mines
        t = self.elapsed()
        key = "look-minas-%d" % self.level
        best = best_get(key)
        rec = best is None or t < best
        if rec:
            best_put(key, t)
        self.redraw()
        self.wm.message("Buscaminas", "¡Has ganado en %d s!%s" % (
            t, "  Nuevo récord." if rec else "  Récord: %d s" % best))

    # ---------------------------------------------------------- geometría y daño
    def cell_at(self, x, y):
        bx, by = 8, self.TOP
        if x < bx or y < by:
            return -1
        cx, cy = (x - bx) // self.CELL, (y - by) // self.CELL
        if 0 <= cx < self.cols and 0 <= cy < self.rows:
            return cy * self.cols + cx
        return -1

    def damage_cell(self, i):
        if self.wm is None:
            return
        cx, cy, cw, ch = self.content()
        self.wm.damage((cx + 8 + (i % self.cols) * self.CELL, cy + self.TOP + (i // self.cols) * self.CELL,
                        self.CELL, self.CELL))

    def damage_header(self):
        if self.wm is None:
            return
        cx, cy, cw, ch = self.content()
        self.wm.damage((cx + 240, cy, cw - 240, self.TOP - 2))

    def tick(self, now):
        if self.t0 is not None and self.over is None:
            t = self.elapsed()
            if t != self.shown_t:
                self.shown_t = t
                self.damage_header()
        return False

    # ---------------------------------------------------------- eventos
    def on_mouse(self, kind, x, y, b):
        if self.over is not None:
            if kind == "down" and y >= self.TOP:
                self.new_game()
            return
        i = self.cell_at(x, y)
        if i < 0:
            return
        if kind == "down":
            self.reveal(i)
        elif kind == "double":
            self.chord(i)
        elif kind == "right":
            self.flag(i)
        self.damage_header()

    def on_key(self, k):
        if k in ("f2", "n", "enter"):
            self.new_game()

    # ---------------------------------------------------------- dibujo
    def draw_content(self, g, x, y, w, h):
        mleft = self.mines - self.flags
        t = self.elapsed()
        face = {"win": "¡Ganado!", "lose": "¡Boom!"}.get(self.over, "")
        g.append(("rect", x + w - 150, y + 10, 64, 28, 0x111827))
        g.append(("text", x + w - 144, y + 14, "%03d" % max(0, mleft), 0xF87171, None))
        g.append(("rect", x + w - 78, y + 10, 64, 28, 0x111827))
        g.append(("text", x + w - 72, y + 14, "%03d" % t, 0xF87171, None))
        if face and w > 480:
            g.append(("text", x + 246, y + 15, face + " (clic: otra)", T["accent"], None))
        C = self.CELL
        for i in range(self.cols * self.rows):
            cx = x + 8 + (i % self.cols) * C
            cy = y + self.TOP + (i // self.cols) * C
            st = self.state[i]
            shown_mine = self.over == "lose" and self.mine[i] and st != 2
            if st == 1 or shown_mine:
                g.append(("rect", cx, cy, C, C, 0xDC2626 if i == self.boom else 0xE5E7EB))
                g.append(("frame", cx, cy, C, C, 0xC4C8CE, 1))
                if shown_mine:
                    g.append(("bitmap", cx + 5, cy + 5, MINE[0], MINE[1], 2))
                elif self.count[i]:
                    g.append(("text", cx + 8, cy + 3, str(self.count[i]), NUM_COLORS[self.count[i]], None))
            else:
                g.append(("rect", cx, cy, C, C, 0xB8C0CC))
                g.append(("rect", cx, cy, C - 1, 2, 0xF3F4F6))
                g.append(("rect", cx, cy, 2, C - 1, 0xF3F4F6))
                g.append(("rect", cx + 1, cy + C - 2, C - 1, 2, 0x6B7280))
                g.append(("rect", cx + C - 2, cy + 1, 2, C - 1, 0x6B7280))
                if st == 2:
                    wrong = self.over == "lose" and not self.mine[i]
                    g.append(("bitmap", cx + 5, cy + 5, FLAG[0], FLAG[1] if not wrong else
                              {"r": 0x9CA3AF, "k": 0x9CA3AF}, 2))


# ================================================================== Serpiente
SNAKE_W, SNAKE_H, SNAKE_C = 28, 20, 18


class SnakeGame(Window):
    icon = "snake"
    resizable = False
    TOP = 34

    def __init__(self):
        Window.__init__(self, "Serpiente", SNAKE_W * SNAKE_C + 16 + 2, SNAKE_H * SNAKE_C + self.TOP + 8 + TITLE_H + 1)
        self.rng = LRng()
        self.best = best_get("look-serpiente") or 0
        self.reset()

    def reset(self):
        cy = SNAKE_H // 2
        self.body = [(6, cy), (5, cy), (4, cy)]
        self.dir = (1, 0)
        self.queue = []
        self.score = 0
        self.state = "ready"          # ready, run, pause, over
        self.next_t = 0
        self.speed = 170
        self.food = None
        self.new_food()
        self.redraw()

    def new_food(self):
        occ = set(self.body)
        free = [(x, y) for y in range(SNAKE_H) for x in range(SNAKE_W) if (x, y) not in occ]
        self.food = free[self.rng.below(len(free))] if free else None

    def dcell(self, c):
        if self.wm is None or c is None:
            return
        cx, cy, cw, ch = self.content()
        self.wm.damage((cx + 8 + c[0] * SNAKE_C, cy + self.TOP + c[1] * SNAKE_C, SNAKE_C, SNAKE_C))

    def dheader(self):
        if self.wm is not None:
            cx, cy, cw, ch = self.content()
            self.wm.damage((cx, cy, cw, self.TOP))

    def tick(self, now):
        if self.state != "run":
            return False
        if now < self.next_t:
            return True
        self.next_t = now + self.speed
        while self.queue:
            d = self.queue.pop(0)
            if (d[0] + self.dir[0], d[1] + self.dir[1]) != (0, 0):
                self.dir = d
                break
        hx, hy = self.body[0]
        nh = (hx + self.dir[0], hy + self.dir[1])
        eat = nh == self.food
        tail = self.body[-1]
        if not (0 <= nh[0] < SNAKE_W and 0 <= nh[1] < SNAKE_H) or (nh in self.body[:-1] if not eat else nh in self.body):
            self.state = "over"
            if self.score > self.best:
                self.best = self.score
                best_put("look-serpiente", self.score)
            self.redraw()
            return False
        self.body.insert(0, nh)
        self.dcell(nh)
        self.dcell(self.body[1])
        if eat:
            self.score += 10
            self.speed = max(60, self.speed - 4)
            self.new_food()
            self.dcell(self.food)
            self.dheader()
        else:
            self.body.pop()
            self.dcell(tail)
        return True

    def on_key(self, k):
        dirs = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
                "w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
        if k in dirs:
            if self.state == "ready":
                self.state = "run"
                self.redraw()
            if len(self.queue) < 3:
                self.queue.append(dirs[k])
        elif k == " ":
            if self.state == "run":
                self.state = "pause"
            elif self.state in ("pause", "ready"):
                self.state = "run"
            self.redraw()
        elif k == "enter" and self.state == "over":
            self.reset()

    def on_mouse(self, kind, x, y, b):
        if kind == "down" and self.state == "over":
            self.reset()

    def draw_content(self, g, x, y, w, h):
        g.append(("text", x + 8, y + 8, "Puntos: %d   Récord: %d" % (self.score, self.best), T["text"], None))
        msg = {"ready": "flechas para empezar", "pause": "pausa (espacio)",
               "over": "fin: Intro o clic para otra", "run": ""}[self.state]
        g.append(("text", x + w - 8 - FW * len(msg), y + 8, msg, T["accent"], None))
        bx, by = x + 8, y + self.TOP
        g.append(("rect", bx, by, SNAKE_W * SNAKE_C, SNAKE_H * SNAKE_C, 0x0B1220))
        if self.food is not None:
            fx, fy = self.food
            g.append(("rect", bx + fx * SNAKE_C + 3, by + fy * SNAKE_C + 3, SNAKE_C - 6, SNAKE_C - 6, 0xEF4444))
        for i, (sx, sy) in enumerate(self.body):
            col = 0x86EFAC if i == 0 else (0x22C55E if self.state != "over" else 0x6B7280)
            g.append(("rect", bx + sx * SNAKE_C + 1, by + sy * SNAKE_C + 1, SNAKE_C - 2, SNAKE_C - 2, col))


# ================================================================== centro de juegos
class GameCenter(Window):
    icon = "games"
    resizable = False

    def __init__(self):
        Window.__init__(self, "Juegos", 460, 300)
        self.add_button(20, 20, 200, 70, "Buscaminas", self.open_mines, True)
        self.add_button(240, 20, 200, 70, "Serpiente", self.open_snake, True)
        self.add_button(20, 110, 420, 50, "Arcade (8 juegos en terminal)", self.open_arcade)

    def open_mines(self):
        self.wm.add(Minesweeper(1))

    def open_snake(self):
        self.wm.add(SnakeGame())

    def open_arcade(self):
        self.wm.add(Terminal(["arcade"], None, "/root", "Arcade"))

    def draw_content(self, g, x, y, w, h):
        lines = ["Buscaminas: clic destapa, clic derecho pone bandera,",
                 "doble clic en un número despeja alrededor.",
                 "Serpiente: flechas o WASD, espacio pausa.",
                 "Récords en /var/games."]
        for i, l in enumerate(lines):
            g.append(("text", x + 20, y + 176 + i * FH, l, T["muted"], None))
