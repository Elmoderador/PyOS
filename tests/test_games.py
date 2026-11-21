"""Juegos 2D del paquete arcade: modo crudo de la consola, pantalla ANSI y lógica."""
import pytest

from pyos.__main__ import run_machine
from pyos.hal.ansi import GridScreen
from pyos.hal.emulated import Raw
from pyos.tools import mkimage
from tests.gamescreen import GameConsole

MEM = 16 << 20


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("g") / "pyos.img")
    mkimage.build(p, size_mb=8)
    return p


def play(image, steps, timeout=20):
    con = GameConsole(steps, timeout=timeout)
    run_machine(image, MEM, lambda: con, max_reboots=1)
    assert "Traceback" not in con.transcript, con.transcript[con.transcript.find("Traceback"):]
    return con


def test_parser_ansi():
    g = GridScreen(20, 5)
    g.write(b"hola\x1b[3;5HX\x1b[1;1H\x1b[K\x1b[2;2Hab\x1b[D\x1b[DZ\x1b[?25l\x1b[31m!")
    assert g.dump().splitlines()[1] == " Z!"
    assert g.dump().splitlines()[2] == "    X"
    g.write(b"\x1b[2")                 # secuencia partida entre dos escrituras
    g.write(b"J")
    assert g.dump().strip() == ""


def test_arcade_viene_instalado(image):
    con = play(image, ["pkg list", "halt"])
    assert "arcade" in con.transcript and "snake tetris pong" in con.transcript


def test_snake_choca_y_guarda_record(image):
    con = play(image, ["snake", Raw(b"q", 4.0), "cat /var/games/snake", "halt"])
    assert con.find("SNAKE", "[]", "<>")
    assert con.find("S N A K E", "Puntos: 0", "Intro: otra")
    assert "root@pyos:/root# cat /var/games/snake" in con.transcript


def test_tetris_mueve_gira_y_suelta(image):
    con = play(image, ["tetris", Raw(b"\x1b[D", 0.5), Raw(b"\x1b[A", 0.2), Raw(b" ", 0.2),
                       Raw(b" ", 0.3), Raw(b"q", 0.5), "halt"])
    snap = con.find("TETRIS", "Siguiente:")
    assert snap and "Puntos  " in snap
    pts = [int(l.split("Puntos")[1].split()[0]) for l in snap.splitlines() if "Puntos" in l]
    assert pts and pts[0] > 0                     # la caída rápida puntúa


@pytest.mark.parametrize("game,keys,needles", [
    ("pong", [b"\x1b[A", b"w"], ["0  :  0"]),
    ("breakout", [b" ", b"\x1b[C"], ["Vidas OOO", "========"]),
    ("invaders", [b" ", b"\x1b[D"], ["Oleada 1", "/▲\\"]),
    ("2048", [b"\x1b[A", b"\x1b[D"], ["2 0 4 8", "+--------+"]),
    ("minas", [b" ", b"f"], ["Minas", "[", "s "]),
])
def test_juegos_arrancan_y_responden(image, game, keys, needles):
    con = play(image, [game] + [Raw(k, 0.4) for k in keys] + [Raw(b"q", 0.4), "echo fin-juego", "halt"])
    assert con.find(*needles), game
    assert "fin-juego" in con.transcript


def test_ctrl_c_restaura_la_consola(image):
    con = play(image, ["snake", Raw(b"\x03", 0.8), "echo consola-normal", "halt"])
    t = con.transcript
    assert "consola-normal" in t[t.rfind("\x1b[2J"):]   # el kernel limpió y devolvió el modo canónico


def test_menu_arcade(image):
    con = play(image, ["arcade", Raw(b"\x1b[B", 0.5), Raw(b"\r", 0.3), Raw(b"q", 1.0),
                       Raw(b"q", 0.8), "halt"])
    assert con.find("Snake", "Tetris", "Minas", "récord")
    assert con.find("TETRIS", "Siguiente:")


def test_flechas_en_modo_canonico_no_ensucian_la_linea(image):
    con = play(image, [Raw(b"ec\x1b[Aho\x1b[D sin-basura\r", 0.3), "halt"])
    assert "sin-basura" in con.transcript and "[A" not in con.transcript.split("sin-basura")[0][-20:]
    assert "orden no encontrada" not in con.transcript
