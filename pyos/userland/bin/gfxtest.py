# /bin/gfxtest — diagnóstico de la pantalla gráfica: adaptador, modo, ratón y una carta
# de ajuste. Sale con cualquier tecla o a los 10 segundos.
def main(argv):
    try:
        info = gfx_open()
    except OSError as e:
        print("gfxtest: %s" % e)
        print(read_file("/proc/gfx").decode(), end="")
        return 1
    ttyctl("raw", True)
    W, H = info["width"], info["height"]
    cols = [0xFFFFFF, 0xFFFF00, 0x00FFFF, 0x00FF00, 0xFF00FF, 0xFF0000, 0x0000FF, 0x000000]
    bw = W // len(cols)
    cmds = [("rect", i * bw, 0, bw, H * 2 // 3, c) for i, c in enumerate(cols)]
    cmds.append(("vgrad", 0, H * 2 // 3, W, H // 3, 0x000000, 0xFFFFFF))
    cmds.append(("rect", W // 2 - 260, H // 2 - 60, 520, 120, 0x202020))
    cmds.append(("text", W // 2 - 248, H // 2 - 48, "PyOS gfxtest  %dx%d" % (W, H), 0xFFFFFF, None))
    cmds.append(("text", W // 2 - 248, H // 2 - 24, str(info.get("adapter", "?"))[:60], 0xA0FFA0, None))
    cmds.append(("text", W // 2 - 248, H // 2, "copia: %s" % info.get("copy", "?"), 0xA0A0FF, None))
    cmds.append(("text", W // 2 - 248, H // 2 + 24, "ratón: %s  — mueve el ratón, una tecla sale"
                 % ("sí" if info.get("mouse") else "no"), 0xFFFFFF, None))
    t0 = uptime_ms()
    gfx_draw(cmds)
    ms = uptime_ms() - t0
    end = uptime_ms() + 10000
    moves = 0
    while uptime_ms() < end:
        ev = gfx_poll(end - uptime_ms())
        moves += len(ev["mouse"])
        if ev["keys"]:
            break
    gfx_close()
    ttyctl("raw", False)
    print("gfxtest: %s %dx%d, carta dibujada en %d ms, %d eventos de ratón"
          % (info.get("adapter", "?"), W, H, ms, moves))
    return 0
