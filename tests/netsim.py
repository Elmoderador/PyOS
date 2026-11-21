"""Red simulada para probar la pila TCP/IP de PyOS sin hardware.

Un "cable" une la NIC del sistema probado con un enrutador simulado que es OTRA
instancia de la misma pila (10.0.2.2) con servidores DHCP, DNS, eco TCP y HTTP
encima. Opcionalmente pierde o desordena tramas para ejercitar las retransmisiones."""
import random
import struct

from pyos.kernel.net.pkt import s2ip, ip2s
from pyos.kernel.net.stack import NetStack, Socket


class SimNIC(object):
    desc = "NIC simulada"

    def __init__(self, mac):
        self.mac = mac
        self.inbox = []
        self.peer = None
        self.loss = 0.0
        self.rng = random.Random(7)

    def send(self, frame):
        if self.loss and self.rng.random() < self.loss:
            return
        self.peer.inbox.append(bytes(frame))

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def link_up(self):
        return True


def wire(a, b):
    a.peer, b.peer = b, a


class Router(object):
    """10.0.2.2: puerta de enlace, DHCP (da 10.0.2.15), DNS y servidores TCP."""
    IP = "10.0.2.2"

    def __init__(self, clock, names=None):
        self.nic = SimNIC(b"\x52\x54\x00\x12\x35\x02")
        rng = random.Random(3)
        self.st = NetStack(self.nic, clock, rand=lambda: rng.getrandbits(32))
        self.st.configure(s2ip(self.IP), s2ip("255.255.255.0"), s2ip(self.IP), s2ip(self.IP), "simulada")
        self.names = names or {"pyos.test": "10.0.2.2", "lejos.test": "93.184.216.34"}
        self.dhcp = Socket(self.st, "udp")
        self.st.udp_bind(self.dhcp, 67)
        self.dns = Socket(self.st, "udp")
        self.st.udp_bind(self.dns, 53)
        self.echo = Socket(self.st, "tcp")
        self.st.tcp_listen(self.echo, 7, 8)
        self.http = Socket(self.st, "tcp")
        self.st.tcp_listen(self.http, 80, 8)
        self.conns = []
        self.page = b"<html><head><title>PyOS</title></head><body><h1>Hola</h1><p>desde la red simulada</p>" \
                    b"<a href=\"/otra\">otra</a></body></html>" + b"x" * 5000

    def step(self):
        for f in self.nic.poll():
            self.st.input(f)
        self.st.tick()
        for data, (ip, port) in self.dhcp.dgrams:
            self._dhcp(data)
        self.dhcp.dgrams = []
        for data, addr in self.dns.dgrams:
            self._dns(data, addr)
        self.dns.dgrams = []
        for lst, kind in ((self.echo, "echo"), (self.http, "http")):
            while lst.backlog:
                c = lst.backlog.pop(0)
                self.conns.append([c, kind, bytearray(), False])
        for ent in self.conns:
            c, kind, buf, done = ent[:4]
            if c.rcvbuf:
                buf += c.rcvbuf
                del c.rcvbuf[:]
            if kind == "echo" and buf:
                n = self.st.tcp_send(c, bytes(buf)) if c.state in ("ESTABLISHED", "CLOSE_WAIT") else 0
                del buf[:n]
            if kind == "echo" and c.peer_fin and not buf and not done:
                self.st.tcp_close(c)
                ent[3] = True
            if kind == "http" and b"\r\n\r\n" in buf and not done:
                path = buf.split(b" ")[1] if b" " in buf else b"/"
                body = self.page if path == b"/" else b"pagina " + path
                resp = (b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n" % len(body)) + body
                ent.append(resp)
                ent[3] = True
            if kind == "http" and len(ent) > 4 and ent[4]:
                n = self.st.tcp_send(c, ent[4]) if c.state in ("ESTABLISHED", "CLOSE_WAIT") else 0
                ent[4] = ent[4][n:]
                if not ent[4]:
                    self.st.tcp_close(c)

    def _dhcp(self, data):
        xid = data[4:8]
        mac = data[28:34]
        i = 240
        mt = 0
        while i < len(data) and data[i] != 255:
            if data[i] == 0:
                i += 1
                continue
            if data[i] == 53:
                mt = data[i + 2]
            i += 2 + data[i + 1]
        rtype = {1: 2, 3: 5}.get(mt)
        if rtype is None:
            return
        self.dhcp_msgs = getattr(self, "dhcp_msgs", []) + [mt]
        if getattr(self, "dhcp_mute", False):
            return
        pkt = struct.pack("!BBBB", 2, 1, 6, 0) + xid + b"\x00\x00\x80\x00" + b"\x00" * 4 + \
            s2ip("10.0.2.15") + s2ip(self.IP) + b"\x00" * 4 + mac + b"\x00" * 10 + b"\x00" * 192 + \
            b"\x63\x82\x53\x63" + bytes([53, 1, rtype, 54, 4]) + s2ip(self.IP) + \
            bytes([1, 4]) + s2ip("255.255.255.0") + bytes([3, 4]) + s2ip(self.IP) + \
            bytes([6, 4]) + s2ip(self.IP) + bytes([51, 4]) + struct.pack("!I", 86400) + b"\xff"
        self.st.udp_sendto(self.dhcp, pkt, (b"\xff" * 4, 68))

    def _dns(self, data, addr):
        qid = data[:2]
        i = 12
        labels = []
        while data[i]:
            labels.append(data[i + 1:i + 1 + data[i]].decode())
            i += 1 + data[i]
        name = ".".join(labels)
        q = data[12:i + 5]
        ip = self.names.get(name)
        if ip:
            ans = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + s2ip(ip)
            msg = qid + b"\x81\x80" + struct.pack("!HHHH", 1, 1, 0, 0) + q + ans
        else:
            msg = qid + b"\x81\x83" + struct.pack("!HHHH", 1, 0, 0, 0) + q
        self.st.udp_sendto(self.dns, msg, addr)


class Clock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class RouterNIC(SimNIC):
    """NIC para la máquina emulada: cada sondeo del kernel hace avanzar al enrutador."""
    desc = "NIC simulada (enrutador 10.0.2.2)"

    def __init__(self, clock):
        SimNIC.__init__(self, b"\x52\x54\x00\x12\x34\x56")
        self.router = Router(clock)
        wire(self, self.router.nic)

    def poll(self):
        self.router.step()
        return SimNIC.poll(self)
