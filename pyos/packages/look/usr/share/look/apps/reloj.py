# /usr/share/look/apps/reloj.py — Reloj y cronómetro: ejemplo de aplicación de terceros para LOOK.
# Cualquier .py de /usr/share/look/apps se carga al arrancar LOOK con acceso a Window, T, FW,
# FH, d_button... (ver docs/LOOK.md). Para aparecer en el menú basta con añadirse a LOOK_APPS.

DIGITS = {
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"], "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"], "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "###"],
    ":": ["...", ".#.", "...", ".#.", "..."], ".": ["...", "...", "...", "...", ".#."],
}


def big_text(g, x, y, s, scale, color):
    for ch in s:
        rows = DIGITS.get(ch)
        if rows is not None:
            g.append(("bitmap", x, y, rows, {"#": color}, scale))
        x += 4 * scale


class Reloj(Window):
    icon = "clock"
    resizable = False

    def __init__(self):
        Window.__init__(self, "Reloj", 420, 300)
        self.running = False
        self.t0 = 0
        self.acc = 0
        self.last = ""
        self.add_button(20, 220, 110, 32, "Empezar", self.toggle, True)
        self.add_button(140, 220, 110, 32, "Poner a 0", self.reset)

    def elapsed(self):
        return self.acc + (uptime_ms() - self.t0 if self.running else 0)

    def toggle(self):
        if self.running:
            self.acc += uptime_ms() - self.t0
            self.running = False
            self.buttons[0].label = "Seguir"
        else:
            self.t0 = uptime_ms()
            self.running = True
            self.buttons[0].label = "Parar"
        self.redraw()

    def reset(self):
        self.running = False
        self.acc = 0
        self.buttons[0].label = "Empezar"
        self.redraw()

    def now(self):
        try:
            off = int(SETTINGS.get("tz", "0"))
        except ValueError:
            off = 0
        s = (int(time()) + off * 3600) % 86400
        return "%02d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)

    def chrono(self):
        ms = self.elapsed()
        return "%02d:%02d.%d" % (ms // 60000, (ms // 1000) % 60, (ms // 100) % 10)

    def tick(self, now):
        key = self.now() + self.chrono()
        if key != self.last:
            self.last = key
            self.redraw()
        return self.running

    def draw_content(self, g, x, y, w, h):
        g.append(("rect", x, y, w, 120, 0x0B1220))
        big_text(g, x + 22, y + 26, self.now(), 10, 0x34D399)
        g.append(("text", x + 20, y + 140, "Cronómetro", T["muted"], None))
        big_text(g, x + 20, y + 164, self.chrono(), 6, T["text"])
        g.append(("text", x + 270, y + 228, "(app de ejemplo)", T["muted"], None))

    def on_key(self, k):
        if k == " ":
            self.toggle()
        elif k in ("r", "0"):
            self.reset()


LOOK_APPS.append(("Reloj", "clock", Reloj))
