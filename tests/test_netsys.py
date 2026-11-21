"""Red de punta a punta: kernel + syscalls + programas de usuario contra el enrutador simulado."""
import time

import pytest

from pyos.__main__ import run_machine
from pyos.hal import emulated
from pyos.hal.emulated import ScriptConsole
from pyos.tools import mkimage
from tests.netsim import RouterNIC


@pytest.fixture
def image(tmp_path):
    p = str(tmp_path / "pyos.img")
    mkimage.build(p, size_mb=16)
    return p


def boot(image, steps, timeout=40):
    orig = emulated.Machine.__init__
    box = {}

    def init(m, *a, **k):
        orig(m, *a, **k)
        m.nic = RouterNIC(m.clock)
        box["router"] = m.nic.router
    emulated.Machine.__init__ = init
    try:
        con = ScriptConsole(steps, timeout=timeout)
        run_machine(image, 16 << 20, lambda: con, max_reboots=1)
    finally:
        emulated.Machine.__init__ = orig
    return con.transcript, box["router"]


def test_dhcp_ping_dns_y_wget(image):
    out, r = boot(image, ["sleep 2", "ifconfig", "ping -c 2 10.0.2.2", "nslookup pyos.test",
                          "ping -c 1 nadie.test", "wget http://pyos.test/ -O /root/web.html",
                          "wget http://pyos.test/otra -O -", "cat /proc/net", "halt"])
    assert "inet 10.0.2.15  máscara 255.255.255.0   (dhcp)" in out
    assert "2 enviados, 2 recibidos, 0% perdidos" in out
    assert "Dirección: 10.0.2.2" in out
    assert "nadie.test: nombre desconocido" in out
    assert "HTTP 200" in out and "-> /root/web.html" in out
    assert "pagina /otra" in out
    assert "10.0.2.2" in out.split("ARP:")[1]


def test_nc_eco(image):
    from pyos.hal.emulated import Raw
    out, r = boot(image, ["sleep 2", "nc 10.0.2.2 7", Raw(b"hola eco\r", 1.0), Raw(b"\x04", 1.0),
                          "halt"])
    assert out.count("hola eco") >= 2


def test_httpd_en_pyos_atiende_al_enrutador(image):
    from pyos.kernel.net.pkt import s2ip
    from pyos.kernel.net.stack import Socket
    got = {}

    def client(router):
        time.sleep(3.0)
        st = router.st
        s = Socket(st, "tcp")
        st.tcp_connect(s, s2ip("10.0.2.15"), 80)
        t0 = time.time()
        while s.state != "ESTABLISHED" and time.time() - t0 < 10:
            time.sleep(0.05)
        st.tcp_send(s, b"GET /estado HTTP/1.0\r\n\r\n")
        while not s.peer_fin and time.time() - t0 < 15:
            time.sleep(0.05)
        got["resp"] = bytes(s.rcvbuf)

    import threading
    orig = emulated.Machine.__init__

    def init(m, *a, **k):
        orig(m, *a, **k)
        m.nic = RouterNIC(m.clock)
        threading.Thread(target=client, args=(m.nic.router,), daemon=True).start()
    emulated.Machine.__init__ = init
    try:
        con = ScriptConsole(["svc start httpd", "sleep 8", "svc stop httpd", "cat /var/log/httpd.log",
                             "halt"], timeout=40)
        run_machine(image, 16 << 20, lambda: con, max_reboots=1)
    finally:
        emulated.Machine.__init__ = orig
    resp = got.get("resp", b"")
    assert resp.startswith(b"HTTP/1.0 200 OK") and b"<h2>Procesos</h2>" in resp, resp[:200]
    assert "httpd: 10.0.2.2 /estado 200" in con.transcript


def test_sin_red(image):
    con = ScriptConsole(["ifconfig", "ping -c 1 1.2.3.4", "ping -c 1 localhost", "svc start httpd",
                         "wget http://127.0.0.1/ -O -", "halt"], timeout=30)
    run_machine(image, 16 << 20, lambda: con, max_reboots=1)
    t = con.transcript
    assert "no hay red" in t and "No route to host" in t
    assert "1 enviados, 1 recibidos" in t                  # ping a localhost
    assert "Servido por PyOS" in t                          # httpd por loopback
