# /bin/look — PyOS LOOK, el entorno gráfico de PyOS.
# Códigos de salida: 0 normal, 2 volver a PyOS Term, 3 apagar, 4 reiniciar, 1 error.


def load_plugins():
    """Carga las aplicaciones de terceros. Un plugin roto no impide arrancar LOOK."""
    try:
        names = sorted(n for n, t in listdir(APPS_DIR) if t != "dir" and n.endswith(".py"))
    except OSError:
        return
    for n in names:
        before = len(LOOK_APPS)
        try:
            include(APPS_DIR + "/" + n)
        except Exception as e:
            del LOOK_APPS[before:]
            PLUGIN_ERRORS.append("%s: %r" % (n, e))


def main(argv):
    t_start = uptime_ms()
    include("/lib/look/icons.py")
    include("/lib/look/core.py")
    include("/lib/look/apps.py")
    include("/lib/look/web.py")
    include("/lib/look/apps2.py")
    include("/lib/look/games.py")
    load_plugins()
    t_loaded = uptime_ms()
    try:
        info = gfx_open()
    except OSError as e:
        print("look: no se puede usar la pantalla gráfica: %s" % e)
        try:
            print(read_file("/proc/gfx").decode(), end="")
        except OSError:
            pass
        return 1
    signal(SIGINT, "ignore")
    ttyctl("raw", "nosig")          # Ctrl+C llega a LOOK como tecla (copiar / interrumpir)
    setfg([getpid()])
    code = 1
    wm = None
    try:
        load_settings()
        wm = WM(info)
        wm.icons = desktop_icons(wm)
        if PLUGIN_ERRORS:
            wm.message("Aplicaciones de terceros",
                       "No se pudieron cargar:\n" + "\n".join(PLUGIN_ERRORS))
        if not info.get("mouse"):
            wm.notice = "sin ratón: Super/F1 menú, flechas e Intro"
        if "--demo" in argv:
            wm.add(About())
            wm.add(Files("/"))
            wm.add(Terminal())
        wm.t_start, wm.t_loaded = t_start, t_loaded
        code = wm.run()
    finally:
        if wm is not None:
            for w in list(wm.wins):
                try:
                    w.on_close()
                except Exception:
                    pass
        gfx_close()
        ttyctl("raw", False)
    if code == 3:
        sync()
        reboot("poweroff")
    elif code == 4:
        sync()
        reboot("reboot")
    return code
