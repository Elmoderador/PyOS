# arcade — menú de los juegos de PyOS.
GAMES = [
    ("snake", "Snake", "come y crece sin morderte"),
    ("tetris", "Tetris", "encaja piezas, haz líneas"),
    ("pong", "Pong", "contra la máquina, a 7"),
    ("breakout", "Breakout", "rompe el muro de ladrillos"),
    ("invaders", "Invaders", "oleadas de alienígenas"),
    ("2048", "2048", "suma fichas hasta 2048"),
    ("minas", "Minas", "buscaminas clásico"),
]
LOGO = [
    " ___  _  _  ___  ___     _   ___  ___   _   ___  ___ ",
    "| _ \\| || |/ _ \\/ __|   /_\\ | _ \\/ __| /_\\ |   \\| __|",
    "|  _/ \\_, | (_) \\__ \\  / _ \\|   / (__ / _ \\| |) | _| ",
    "|_|   |__/ \\___/|___/ /_/ \\_\\_|_\\\\___/_/ \\_\\___/|___|",
]


def menu(scr):
    sel = 0
    while True:
        scr.clear()
        top = max(1, (scr.rows - 22) // 2)
        for i, line in enumerate(LOGO):
            scr.center(top + i, line)
        w = 56
        left = (scr.cols - w) // 2
        scr.box(top + 6, left, len(GAMES) + 4, w, True)
        for i, (prog, name, desc) in enumerate(GAMES):
            mark = RIGHT if i == sel else " "
            best = highscore(prog)
            line = "%s %d. %-9s %-26s %7s" % (mark, i + 1, name, desc, best if best else "-")
            scr.put(top + 8 + i, left + 2, line)
        scr.put(top + 7, left + 44, "récord")
        scr.center(top + len(GAMES) + 11, "↑/↓ elegir · Intro jugar · número directo · Q salir")
        scr.present()
        k = scr.wait_key()
        if k in ("q", "esc"):
            return None
        if k in ("up", "w"):
            sel = (sel - 1) % len(GAMES)
        elif k in ("down", "s"):
            sel = (sel + 1) % len(GAMES)
        elif k in ("enter", "space"):
            return GAMES[sel][0]
        elif len(k) == 1 and "1" <= k <= str(len(GAMES)):
            return GAMES[int(k) - 1][0]


def main(argv):
    include("/lib/tui.py")
    while True:
        prog = run_game(menu)
        if prog is None:
            return 0
        pid = spawn("/bin/" + prog + ".py", [prog])
        setfg([pid])
        waitpid(pid)
        setfg([getpid()])
