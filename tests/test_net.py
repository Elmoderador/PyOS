"""Pila TCP/IP de PyOS contra un enrutador simulado (otra instancia de la pila)."""
import random

import pytest

from pyos.kernel.net.pkt import checksum, ip2s, ipv4, pseudo_sum, s2ip, udp
from pyos.kernel.net.stack import NetStack, Socket
from tests.netsim import Clock, Router, SimNIC, wire


def make(loss=0.0):
    clk = Clock()
    r = Router(clk)
    nic = SimNIC(b"\x52\x54\x00\x12\x34\x56")
    wire(nic, r.nic)
    nic.loss = loss
    r.nic.loss = loss
    rng = random.Random(11)
    st = NetStack(nic, clk, rand=lambda: rng.getrandbits(32))
    return clk, r, nic, st


def run(clk, r, nic, st, secs, until=None, dt=0.01):
    end = clk.t + secs
    while clk.t < end:
        for f in nic.poll():
            st.input(f)
        st.tick()
        r.step()
        if until is not None and until():
            return True
        clk.t += dt
    return until() if until is not None else True


def test_sumas_de_comprobacion():
    h = ipv4(s2ip("10.0.0.1"), s2ip("10.0.0.2"), 17, b"abc", 7)
    assert checksum(h[:20]) == 0
    u = udp(s2ip("1.2.3.4"), s2ip("5.6.7.8"), 1000, 53, b"x" * 13)
    assert checksum(u, pseudo_sum(s2ip("1.2.3.4"), s2ip("5.6.7.8"), 17, len(u))) == 0


def test_dhcp_configura_la_interfaz():
    clk, r, nic, st = make()
    st.dhcp_start()
    assert run(clk, r, nic, st, 10, lambda: st.configured)
    i = st.info()
    assert (i["ip"], i["gw"], i["dns"], i["mask"]) == ("10.0.2.15", "10.0.2.2", "10.0.2.2", "255.255.255.0")


def test_dhcp_renueva_y_caduca():
    clk, r, nic, st = make()
    st.dhcp_start()
    assert run(clk, r, nic, st, 10, lambda: st.configured)
    r.dhcp_msgs = []
    clk.t += 43200                           # T1: mitad de la concesión de 86400 s
    assert run(clk, r, nic, st, 5, lambda: r.dhcp_msgs == [3] and st.dhcp["state"] == "BOUND")
    assert st.configured and st.info()["ip"] == "10.0.2.15"
    # servidor caído: se mantiene la IP mientras la concesión sea válida...
    r.dhcp_mute = True
    clk.t += 43200
    run(clk, r, nic, st, 30)
    assert st.configured and st.dhcp["state"] == "BOUND" and st.dhcp["renew_at"] is not None
    # ...y al caducar se vuelve a DISCOVER
    clk.t += 86400
    run(clk, r, nic, st, 30)
    assert 1 in r.dhcp_msgs and st.dhcp["state"] in ("DISCOVER", "FAILED")


def configured(loss=0.0):
    clk, r, nic, st = make(loss)
    st.configure(s2ip("10.0.2.15"), s2ip("255.255.255.0"), s2ip("10.0.2.2"), s2ip("10.0.2.2"))
    return clk, r, nic, st


def test_ping_y_arp():
    clk, r, nic, st = configured()
    st.ping_send(s2ip("10.0.2.2"), 77, 1)
    assert run(clk, r, nic, st, 3, lambda: st.ping_result(77, 1) is not None)
    assert s2ip("10.0.2.2") in st.arp
    # al revés: el enrutador hace ping a PyOS y PyOS responde
    r.st.ping_send(s2ip("10.0.2.15"), 5, 9)
    assert run(clk, r, nic, st, 3, lambda: r.st.ping_result(5, 9) is not None)


def test_ping_a_host_inexistente_no_responde():
    clk, r, nic, st = configured()
    st.ping_send(s2ip("10.0.2.99"), 1, 1)
    run(clk, r, nic, st, 5)
    assert st.ping_result(1, 1) is None and not st.arp_pending


def test_dns():
    clk, r, nic, st = configured()
    q = st.resolve_start("pyos.test")
    assert run(clk, r, nic, st, 5, lambda: q["done"])
    assert [ip2s(x) for x in q["result"]] == ["10.0.2.2"]
    q2 = st.resolve_start("pyos.test")             # caché
    assert q2["done"] and q2["result"] == q["result"]
    q3 = st.resolve_start("noexiste.test")
    assert run(clk, r, nic, st, 5, lambda: q3["done"])
    assert q3["result"] == [] and q3.get("error") == "NXDOMAIN"


def tcp_echo(loss):
    clk, r, nic, st = configured(loss)
    s = Socket(st, "tcp")
    st.tcp_connect(s, s2ip("10.0.2.2"), 7)
    assert run(clk, r, nic, st, 30, lambda: s.state == "ESTABLISHED")
    data = bytes(random.Random(1).getrandbits(8) for _ in range(40000))
    sent = 0
    got = bytearray()

    def progress():
        nonlocal sent
        if sent < len(data):
            sent += st.tcp_send(s, data[sent:sent + 8000])
        got.extend(s.rcvbuf)
        del s.rcvbuf[:]
        return len(got) >= len(data)
    assert run(clk, r, nic, st, 120, progress), (len(got), sent)
    assert bytes(got) == data
    st.tcp_close(s)
    assert run(clk, r, nic, st, 60, lambda: s.state == "CLOSED")
    assert not st.tcp_conns


def test_tcp_eco_sin_perdidas():
    tcp_echo(0.0)


def test_tcp_eco_con_perdidas_retransmite():
    tcp_echo(0.08)


def test_tcp_puerto_cerrado_rechaza():
    clk, r, nic, st = configured()
    s = Socket(st, "tcp")
    st.tcp_connect(s, s2ip("10.0.2.2"), 9999)
    assert run(clk, r, nic, st, 5, lambda: s.state == "CLOSED")
    assert s.error == 111


def test_tcp_sin_respuesta_caduca():
    clk, r, nic, st = configured()
    r.nic.loss = 1.0                                 # el otro extremo no responde nunca
    st.arp[s2ip("10.0.2.2")] = (r.nic.mac, 1e9)
    s = Socket(st, "tcp")
    st.tcp_connect(s, s2ip("10.0.2.2"), 7)
    run(clk, r, nic, st, 200, lambda: s.state == "CLOSED", dt=0.1)
    assert s.state == "CLOSED" and s.error == 110


def test_servidor_tcp_en_pyos():
    clk, r, nic, st = configured()
    lst = Socket(st, "tcp")
    st.tcp_listen(lst, 8080, 4)
    c = Socket(r.st, "tcp")
    r.st.tcp_connect(c, s2ip("10.0.2.15"), 8080)
    assert run(clk, r, nic, st, 5, lambda: lst.backlog)
    srv = lst.backlog.pop(0)
    st.tcp_send(srv, b"bienvenido")
    st.tcp_close(srv)
    assert run(clk, r, nic, st, 10, lambda: c.peer_fin)
    assert bytes(c.rcvbuf) == b"bienvenido"


def test_http_get():
    clk, r, nic, st = configured()
    s = Socket(st, "tcp")
    st.tcp_connect(s, s2ip("10.0.2.2"), 80)
    assert run(clk, r, nic, st, 5, lambda: s.state == "ESTABLISHED")
    st.tcp_send(s, b"GET / HTTP/1.0\r\nHost: pyos.test\r\n\r\n")
    assert run(clk, r, nic, st, 20, lambda: s.peer_fin)
    body = bytes(s.rcvbuf)
    assert body.startswith(b"HTTP/1.0 200 OK") and b"<h1>Hola</h1>" in body and body.endswith(b"x" * 100)
