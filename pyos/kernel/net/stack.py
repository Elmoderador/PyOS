"""Pila TCP/IP de PyOS: Ethernet, ARP, IPv4, ICMP, UDP, TCP, cliente DHCP y DNS.

Escrita en Python, sin hilos: la alimentan las tramas que entrega el driver de red
(`input`) y un reloj (`tick`). No bloquea nunca: las operaciones que esperan (connect,
recv, accept, ping, resolver un nombre) dejan el estado en el socket y avisan por su
cola de espera cuando algo cambia; el kernel reintenta la syscall al despertar.

Simplificaciones conscientes (documentadas en docs/NET.md):
  * IPv4 sin fragmentación (los fragmentos se descartan; se envía con DF).
  * TCP: ventana fija, sin control de congestión, segmentos fuera de orden descartados
    (el emisor retransmite), retransmisión con RTO exponencial (1 s .. 16 s).
  * DHCP sin renovación de la concesión (VirtualBox/QEMU dan concesiones largas).
"""
import struct

from .pkt import (BROADCAST_MAC, ETH_ARP, ETH_IP, PROTO_ICMP, PROTO_TCP, PROTO_UDP,
                  checksum, eth, ip2s, ipv4, pseudo_sum, s2ip, tcp, udp)

ZERO_IP = b"\x00" * 4
LOOPBACK = b"\x7f\x00\x00\x01"
BCAST_IP = b"\xff" * 4
MSS = 1460
RCV_WINDOW = 32768
SNDBUF_MAX = 65536
RCVBUF_MAX = 65536

FIN, SYN, RST, PSH, ACK = 0x01, 0x02, 0x04, 0x08, 0x10

# errores (mismos números que el kernel)
ECONNREFUSED, ETIMEDOUT, ECONNRESET, EHOSTUNREACH, ENOTCONN = 111, 110, 104, 113, 107
EADDRINUSE, EPIPE = 98, 32


def seq_lt(a, b):
    return ((a - b) & 0xFFFFFFFF) > 0x7FFFFFFF


def seq_le(a, b):
    return a == b or seq_lt(a, b)


class _DummyWQ(object):
    def wake_all(self):
        pass


class Socket(object):
    """Socket TCP o UDP del kernel (el fichero del proceso apunta aquí)."""

    def __init__(self, stack, kind):
        self.stack = stack
        self.kind = kind                    # "tcp" | "udp"
        self.wq = stack.make_wq("sock")
        self.lport = 0
        self.raddr = None                   # (ip bytes, puerto)
        self.state = "CLOSED"
        self.error = 0
        # UDP
        self.dgrams = []
        # TCP
        self.backlog = []
        self.max_backlog = 0
        self.parent = None
        self.rcvbuf = bytearray()
        self.sndbuf = bytearray()           # datos desde snd_una (incluye lo enviado sin ack)
        self.snd_una = self.snd_nxt = self.iss = 0
        self.rcv_nxt = 0
        self.peer_win = MSS
        self.peer_mss = 536
        self.fin_pending = False            # close() pedido: FIN tras vaciar sndbuf
        self.fin_sent = False
        self.fin_seq = None
        self.peer_fin = False
        self.rto = 1.0
        self.retries = 0
        self.timer = None                   # instante de retransmisión
        self.tw_until = None
        self.connecting = False
        self.closed_by_user = False

    def wake(self):
        self.wq.wake_all()
        if self.parent is not None:
            self.parent.wq.wake_all()

    def describe(self):
        local = "%s:%d" % (ip2s(self.stack.ip), self.lport)
        remote = "%s:%d" % (ip2s(self.raddr[0]), self.raddr[1]) if self.raddr else "*:*"
        return "%-4s %-22s %-22s %s" % (self.kind, local, remote, self.state)


class NetStack(object):
    def __init__(self, nic, clock, log=None, make_wq=None, rand=None):
        self.nic = nic
        self.mac = nic.mac
        self.clock = clock
        self.log = log or (lambda *a: None)
        self.make_wq = make_wq or (lambda name: _DummyWQ())
        self.rand = rand or (lambda: 0x12345678)
        self.ip = ZERO_IP
        self.mask = ZERO_IP
        self.gw = ZERO_IP
        self.dns = ZERO_IP
        self.configured = False
        self.method = "ninguno"
        self.arp = {}                       # ip -> (mac, caduca)
        self.arp_pending = {}               # ip -> [paquetes, reintentos, próximo]
        self.ip_id = self.rand() & 0xFFFF
        self.udp_ports = {}
        self.tcp_conns = {}                 # (lport, rip, rport) -> Socket
        self.listeners = {}                # lport -> Socket
        self.next_port = 49152 + (self.rand() % 10000)
        self.pings = {}                     # (id, seq) -> [enviado, rtt o None, wq, ttl]
        self.dhcp = None
        self.dns_q = {}                     # id -> consulta
        self.dns_cache = {}
        self.stats = {"rx": 0, "tx": 0, "rx_bytes": 0, "tx_bytes": 0, "drop": 0}
        self.loop_q = []                    # paquetes IP hacia 127.0.0.0/8 o a nuestra IP
        self.cfg_wq = self.make_wq("dhcp")

    # ================================================================ configuración
    def configure(self, ip, mask, gw, dns, method="estática"):
        self.ip, self.mask, self.gw, self.dns = ip, mask, gw, dns
        self.configured = ip != ZERO_IP
        self.method = method
        self.log("net: %s %s/%s puerta %s dns %s" % (method, ip2s(ip), ip2s(mask), ip2s(gw), ip2s(dns)))
        self.cfg_wq.wake_all()

    def info(self):
        return {"mac": ":".join("%02x" % b for b in self.mac), "ip": ip2s(self.ip),
                "mask": ip2s(self.mask), "gw": ip2s(self.gw), "dns": ip2s(self.dns),
                "configured": self.configured, "method": self.method,
                "driver": getattr(self.nic, "desc", "?"),
                "link": bool(getattr(self.nic, "link_up", lambda: True)()),
                "stats": dict(self.stats),
                "dhcp": self.dhcp["state"] if self.dhcp else "—"}

    # ================================================================ capa de enlace
    def _send_eth(self, dst_mac, etype, payload):
        frame = eth(dst_mac, self.mac, etype, payload)
        if len(frame) < 60:
            frame += b"\x00" * (60 - len(frame))
        self.stats["tx"] += 1
        self.stats["tx_bytes"] += len(frame)
        self.nic.send(frame)

    def input(self, frame):
        if len(frame) < 14:
            return
        self.stats["rx"] += 1
        self.stats["rx_bytes"] += len(frame)
        dst = frame[0:6]
        if dst != self.mac and dst != BROADCAST_MAC and not dst[0] & 1:
            return
        etype = struct.unpack("!H", frame[12:14])[0]
        if etype == ETH_ARP:
            self._arp_in(frame[14:])
        elif etype == ETH_IP:
            self._ip_in(frame[14:])

    # ================================================================ ARP
    def _arp_in(self, p):
        if len(p) < 28:
            return
        htype, ptype, hl, pl, op = struct.unpack("!HHBBH", p[:8])
        if htype != 1 or ptype != ETH_IP:
            return
        sha, spa, tha, tpa = p[8:14], p[14:18], p[18:24], p[24:28]
        now = self.clock()
        if spa != ZERO_IP:
            self.arp[spa] = (sha, now + 300)
            pend = self.arp_pending.pop(spa, None)
            if pend:
                for etype, payload in pend[0]:
                    self._send_eth(sha, etype, payload)
        if op == 1 and tpa == self.ip and self.configured:
            reply = struct.pack("!HHBBH", 1, ETH_IP, 6, 4, 2) + self.mac + self.ip + sha + spa
            self._send_eth(sha, ETH_ARP, reply)

    def _arp_request(self, ip):
        req = struct.pack("!HHBBH", 1, ETH_IP, 6, 4, 1) + self.mac + self.ip + b"\x00" * 6 + ip
        self._send_eth(BROADCAST_MAC, ETH_ARP, req)

    def _next_hop(self, dst):
        if dst == BCAST_IP:
            return dst
        m = self.mask
        if all((a & k) == (b & k) for a, b, k in zip(dst, self.ip, m)):
            return dst
        return self.gw

    def src_for(self, dst):
        return LOOPBACK if dst[0] == 127 else self.ip

    def is_local(self, dst):
        return dst[0] == 127 or (self.configured and dst == self.ip)

    def loopback(self):
        """Entrega los paquetes locales (los llama el kernel junto con la recepción)."""
        n = 0
        while self.loop_q and n < 256:
            self._ip_in(self.loop_q.pop(0))
            n += 1

    def _send_ip(self, dst, proto, payload, src=None):
        self.ip_id = (self.ip_id + 1) & 0xFFFF
        pkt = ipv4(src if src is not None else self.src_for(dst), dst, proto, payload, self.ip_id)
        if self.is_local(dst):
            self.loop_q.append(pkt)
            return True
        hop = self._next_hop(dst)
        if hop == BCAST_IP:
            self._send_eth(BROADCAST_MAC, ETH_IP, pkt)
            return True
        if hop == ZERO_IP:
            return False
        ent = self.arp.get(hop)
        if ent and ent[1] > self.clock():
            self._send_eth(ent[0], ETH_IP, pkt)
            return True
        pend = self.arp_pending.get(hop)
        if pend is None:
            self.arp_pending[hop] = [[(ETH_IP, pkt)], 1, self.clock() + 1.0]
            self._arp_request(hop)
        elif len(pend[0]) < 16:
            pend[0].append((ETH_IP, pkt))
        return True

    # ================================================================ IPv4
    def _ip_in(self, p):
        if len(p) < 20 or p[0] >> 4 != 4:
            return
        ihl = (p[0] & 15) * 4
        total = struct.unpack("!H", p[2:4])[0]
        if total > len(p) or ihl < 20 or checksum(p[:ihl]) != 0:
            self.stats["drop"] += 1
            return
        frag = struct.unpack("!H", p[6:8])[0]
        if frag & 0x3FFF:                   # fragmentos: no soportados
            self.stats["drop"] += 1
            return
        proto = p[9]
        src, dst = p[12:16], p[16:20]
        if dst != self.ip and dst != BCAST_IP and dst[0] != 127 and self.configured:
            return
        body = p[ihl:total]
        if proto == PROTO_ICMP:
            self._icmp_in(src, body)
        elif proto == PROTO_UDP:
            self._udp_in(src, dst, body)
        elif proto == PROTO_TCP and (self.configured or dst[0] == 127):
            self._tcp_in(src, dst, body)

    # ================================================================ ICMP
    def _icmp_in(self, src, b):
        if len(b) < 8 or checksum(b) != 0:
            return
        typ, code, _, ident, seq = struct.unpack("!BBHHH", b[:8])
        if typ == 8 and (self.configured or src[0] == 127):   # eco: responder
            rep = struct.pack("!BBHHH", 0, 0, 0, ident, seq) + b[8:]
            c = checksum(rep)
            self._send_ip(src, PROTO_ICMP, rep[:2] + struct.pack("!H", c) + rep[4:])
        elif typ == 0:
            ent = self.pings.get((ident, seq))
            if ent is not None and ent[1] is None:
                ent[1] = self.clock() - ent[0]
                ent[3] = src
                ent[2].wake_all()

    def ping_send(self, dst, ident, seq, size=56):
        data = bytes((i & 0xFF) for i in range(size))
        req = struct.pack("!BBHHH", 8, 0, 0, ident, seq) + data
        c = checksum(req)
        wq = self.make_wq("ping")
        self.pings[(ident, seq)] = [self.clock(), None, wq, None]
        self._send_ip(dst, PROTO_ICMP, req[:2] + struct.pack("!H", c) + req[4:])
        return wq

    def ping_result(self, ident, seq):
        ent = self.pings.get((ident, seq))
        return None if ent is None else ent[1]

    def ping_forget(self, ident, seq):
        self.pings.pop((ident, seq), None)

    # ================================================================ UDP
    def _udp_in(self, src, dst, b):
        if len(b) < 8:
            return
        sport, dport, ln, csum = struct.unpack("!HHHH", b[:8])
        if ln > len(b) or ln < 8:
            return
        if csum and checksum(b[:ln], pseudo_sum(src, dst, PROTO_UDP, ln)) != 0:
            self.stats["drop"] += 1
            return
        data = bytes(b[8:ln])
        if dport == 68 and self.dhcp is not None:
            self._dhcp_in(data)
            return
        if dport in self._dns_ports():
            self._dns_in(dport, data)
            return
        s = self.udp_ports.get(dport)
        if s is not None and len(s.dgrams) < 64:
            s.dgrams.append((data, (src, sport)))
            s.wake()

    def alloc_port(self):
        for _ in range(16384):
            p = self.next_port
            self.next_port = 49152 if self.next_port >= 65535 else self.next_port + 1
            if p not in self.udp_ports and p not in self.listeners and \
                    not any(k[0] == p for k in self.tcp_conns):
                return p
        raise OSError(EADDRINUSE, "sin puertos libres")

    def udp_bind(self, s, port):
        if port == 0:
            port = self.alloc_port()
        if port in self.udp_ports:
            raise OSError(EADDRINUSE, "puerto UDP en uso")
        s.lport = port
        self.udp_ports[port] = s
        s.state = "BOUND"

    def udp_sendto(self, s, data, addr):
        if not s.lport:
            self.udp_bind(s, 0)
        if not self.configured and addr[0] != BCAST_IP and addr[0][0] != 127:
            raise OSError(EHOSTUNREACH, "red sin configurar")
        self._send_ip(addr[0], PROTO_UDP, udp(self.src_for(addr[0]), addr[0], s.lport, addr[1], data))
        return len(data)

    # ================================================================ TCP
    def _tcp_send(self, s, flags, payload=b"", seq=None, mss=None):
        sq = s.snd_nxt if seq is None else seq
        win = max(0, RCVBUF_MAX - len(s.rcvbuf))
        seg = tcp(self.src_for(s.raddr[0]), s.raddr[0], s.lport, s.raddr[1], sq, s.rcv_nxt, flags, win,
                  payload, mss)
        self._send_ip(s.raddr[0], PROTO_TCP, seg)

    def _rst_for(self, src, dst, sport, dport, seq, ack, flags, plen):
        if flags & RST:
            return
        if flags & ACK:
            seg = tcp(dst, src, dport, sport, ack, 0, RST, 0)
        else:
            seg = tcp(dst, src, dport, sport, 0, seq + plen + (1 if flags & SYN else 0)
                      + (1 if flags & FIN else 0), RST | ACK, 0)
        self._send_ip(src, PROTO_TCP, seg)

    def tcp_connect(self, s, ip, port):
        if not self.configured and ip[0] != 127:
            raise OSError(EHOSTUNREACH, "red sin configurar")
        if not s.lport:
            s.lport = self.alloc_port()
        s.raddr = (ip, port)
        s.iss = self.rand() & 0xFFFFFFFF
        s.snd_una = s.iss
        s.snd_nxt = (s.iss + 1) & 0xFFFFFFFF
        s.state = "SYN_SENT"
        s.connecting = True
        self.tcp_conns[(s.lport, ip, port)] = s
        self._tcp_send(s, SYN, seq=s.iss, mss=MSS)
        self._arm(s)

    def tcp_listen(self, s, port, backlog):
        if port in self.listeners:
            raise OSError(EADDRINUSE, "puerto TCP en uso")
        s.lport = port
        s.state = "LISTEN"
        s.max_backlog = max(1, min(16, backlog))
        self.listeners[port] = s

    def _arm(self, s):
        s.timer = self.clock() + s.rto

    def _parse_mss(self, b, off):
        i = 20
        while i < off:
            kind = b[i]
            if kind == 0:
                break
            if kind == 1:
                i += 1
                continue
            if i + 1 >= off:
                break
            ln = b[i + 1]
            if kind == 2 and ln == 4:
                return struct.unpack("!H", b[i + 2:i + 4])[0]
            i += max(2, ln)
        return 536

    def _tcp_in(self, src, dst, b):
        if len(b) < 20 or checksum(b, pseudo_sum(src, dst, PROTO_TCP, len(b))) != 0:
            self.stats["drop"] += 1
            return
        sport, dport, seq, ack, offb, flags, win = struct.unpack("!HHIIBBH", b[:16])
        off = (offb >> 4) * 4
        payload = bytes(b[off:])
        s = self.tcp_conns.get((dport, src, sport))
        if s is None:
            lst = self.listeners.get(dport)
            if lst is not None and flags & SYN and not flags & ACK:
                if len(lst.backlog) >= lst.max_backlog:
                    return
                c = Socket(self, "tcp")
                c.parent = lst
                c.lport = dport
                c.raddr = (src, sport)
                c.rcv_nxt = (seq + 1) & 0xFFFFFFFF
                c.iss = self.rand() & 0xFFFFFFFF
                c.snd_una = c.iss
                c.snd_nxt = (c.iss + 1) & 0xFFFFFFFF
                c.peer_win = win
                c.peer_mss = self._parse_mss(b, off)
                c.state = "SYN_RCVD"
                self.tcp_conns[(dport, src, sport)] = c
                self._tcp_send(c, SYN | ACK, seq=c.iss, mss=MSS)
                self._arm(c)
                return
            self._rst_for(src, dst, sport, dport, seq, ack, flags, len(payload))
            return
        self._tcp_segment(s, seq, ack, flags, win, payload, b, off)

    def _tcp_segment(self, s, seq, ack, flags, win, payload, b, off):
        if flags & RST:
            if s.state == "SYN_SENT":
                if flags & ACK and ack == s.snd_nxt:
                    self._tcp_fail(s, ECONNREFUSED)
                return
            if seq_le(s.rcv_nxt, seq) and seq_lt(seq, (s.rcv_nxt + RCV_WINDOW) & 0xFFFFFFFF) or seq == s.rcv_nxt:
                self._tcp_fail(s, ECONNRESET)
            return
        if s.state == "SYN_SENT":
            if flags & SYN and flags & ACK and ack == s.snd_nxt:
                s.rcv_nxt = (seq + 1) & 0xFFFFFFFF
                s.snd_una = ack
                s.peer_win = win
                s.peer_mss = self._parse_mss(b, off)
                s.state = "ESTABLISHED"
                s.timer = None
                s.retries = 0
                s.rto = 1.0
                self._tcp_send(s, ACK)
                s.wake()
            return
        # comprobación de secuencia: solo en orden (lo demás -> ACK duplicado)
        if seq != s.rcv_nxt and not (flags & SYN):
            if payload or flags & FIN:
                self._tcp_send(s, ACK)
            if not flags & ACK:
                return
            payload = b""
            flags &= ~FIN
        if flags & ACK:
            self._tcp_ack(s, ack, win)
        if s.state == "SYN_RCVD":
            return
        if payload and s.state in ("ESTABLISHED", "FIN_WAIT_1", "FIN_WAIT_2"):
            room = RCVBUF_MAX - len(s.rcvbuf)
            data = payload[:room]
            if data:
                s.rcvbuf += data
                s.rcv_nxt = (s.rcv_nxt + len(data)) & 0xFFFFFFFF
                s.wake()
            self._tcp_send(s, ACK)
        if flags & FIN and seq_le(seq, s.rcv_nxt) and not s.peer_fin:
            s.peer_fin = True
            s.rcv_nxt = (s.rcv_nxt + 1) & 0xFFFFFFFF
            self._tcp_send(s, ACK)
            if s.state == "ESTABLISHED":
                s.state = "CLOSE_WAIT"
            elif s.state == "FIN_WAIT_1":
                s.state = "CLOSING"
            elif s.state == "FIN_WAIT_2":
                self._time_wait(s)
            s.wake()

    def _tcp_ack(self, s, ack, win):
        if seq_lt(s.snd_una, ack) and seq_le(ack, s.snd_nxt):
            acked = (ack - s.snd_una) & 0xFFFFFFFF
            if s.state == "SYN_RCVD":
                acked -= 1                   # el SYN
                s.state = "ESTABLISHED"
                if s.parent is not None and s.parent.state == "LISTEN":
                    s.parent.backlog.append(s)
                    s.parent.wq.wake_all()
            if s.fin_sent and ack == s.snd_nxt:
                acked -= 1                   # el FIN
                if s.state == "FIN_WAIT_1":
                    s.state = "FIN_WAIT_2"
                elif s.state == "CLOSING":
                    self._time_wait(s)
                elif s.state == "LAST_ACK":
                    self._tcp_drop(s)
            if acked > 0:
                del s.sndbuf[:acked]
            s.snd_una = ack
            s.retries = 0
            s.rto = 1.0
            s.timer = None if s.snd_una == s.snd_nxt else self.clock() + s.rto
            s.wake()
        s.peer_win = win
        self._tcp_output(s)

    def _tcp_output(self, s):
        """Envía lo que quepa en la ventana del otro extremo; luego el FIN si toca."""
        if s.state not in ("ESTABLISHED", "CLOSE_WAIT", "FIN_WAIT_1", "LAST_ACK", "CLOSING"):
            return
        sent = (s.snd_nxt - s.snd_una) & 0xFFFFFFFF
        if s.fin_sent:
            sent -= 1
        while sent < len(s.sndbuf):
            in_flight = sent
            room = max(s.peer_win, 1 if in_flight == 0 else 0) - in_flight
            if room <= 0:
                break
            n = min(len(s.sndbuf) - sent, s.peer_mss, room)
            chunk = bytes(s.sndbuf[sent:sent + n])
            self._tcp_send(s, ACK | PSH, chunk, seq=(s.snd_una + sent) & 0xFFFFFFFF)
            sent += n
            s.snd_nxt = (s.snd_una + sent) & 0xFFFFFFFF
            if s.timer is None:
                self._arm(s)
        if s.fin_pending and not s.fin_sent and sent >= len(s.sndbuf):
            s.fin_seq = s.snd_nxt
            self._tcp_send(s, FIN | ACK, seq=s.snd_nxt)
            s.snd_nxt = (s.snd_nxt + 1) & 0xFFFFFFFF
            s.fin_sent = True
            if s.state == "ESTABLISHED":
                s.state = "FIN_WAIT_1"
            elif s.state == "CLOSE_WAIT":
                s.state = "LAST_ACK"
            if s.timer is None:
                self._arm(s)

    def tcp_send(self, s, data):
        if s.state not in ("ESTABLISHED", "CLOSE_WAIT"):
            raise OSError(s.error or EPIPE, "conexión cerrada")
        if s.fin_pending:
            raise OSError(EPIPE, "conexión cerrada")
        room = SNDBUF_MAX - len(s.sndbuf)
        if room <= 0:
            return 0
        data = data[:room]
        s.sndbuf += data
        self._tcp_output(s)
        return len(data)

    def tcp_close(self, s):
        s.closed_by_user = True
        if s.state == "LISTEN":
            self.listeners.pop(s.lport, None)
            for c in s.backlog:
                self.tcp_close(c)
            s.backlog = []
            s.state = "CLOSED"
            return
        if s.state in ("SYN_SENT", "CLOSED", "SYN_RCVD"):
            if s.state == "SYN_RCVD":
                self._tcp_send(s, RST, seq=s.snd_nxt)
            self._tcp_drop(s)
            return
        if s.state in ("ESTABLISHED", "CLOSE_WAIT"):
            s.fin_pending = True
            self._tcp_output(s)

    def _time_wait(self, s):
        s.state = "TIME_WAIT"
        s.timer = None
        s.tw_until = self.clock() + 2.0
        s.wake()

    def _tcp_fail(self, s, err):
        s.error = err
        self._tcp_drop(s)

    def _tcp_drop(self, s):
        if s.raddr is not None:
            self.tcp_conns.pop((s.lport, s.raddr[0], s.raddr[1]), None)
        if s.state != "CLOSED":
            s.state = "CLOSED"
        s.timer = None
        if s.parent is not None and s in s.parent.backlog:
            s.parent.backlog.remove(s)
        s.wake()

    # ================================================================ reloj
    def tick(self):
        now = self.clock()
        for ip, pend in list(self.arp_pending.items()):
            if now >= pend[2]:
                if pend[1] >= 3:
                    del self.arp_pending[ip]
                    self._unreachable(ip)
                else:
                    pend[1] += 1
                    pend[2] = now + 1.0
                    self._arp_request(ip)
        for s in list(self.tcp_conns.values()):
            if s.tw_until is not None and now >= s.tw_until:
                self._tcp_drop(s)
                continue
            if s.timer is not None and now >= s.timer:
                self._retransmit(s)
        if self.dhcp is not None:
            self._dhcp_tick(now)
        for qid, q in list(self.dns_q.items()):
            if now >= q["deadline"]:
                if q["tries"] < 3:
                    q["tries"] += 1
                    q["deadline"] = now + 2.0
                    self._dns_send(qid, q)
                else:
                    q["result"] = []
                    q["done"] = True
                    del self.dns_q[qid]
                    self.udp_ports.pop(q["port"], None)
                    q["wq"].wake_all()

    def _unreachable(self, ip):
        for s in list(self.tcp_conns.values()):
            if s.state == "SYN_SENT" and self._next_hop(s.raddr[0]) == ip:
                self._tcp_fail(s, EHOSTUNREACH)

    def _retransmit(self, s):
        s.retries += 1
        if s.retries > 8 or (s.state in ("SYN_SENT", "SYN_RCVD") and s.retries > 5):
            self._tcp_fail(s, ETIMEDOUT)
            return
        s.rto = min(16.0, s.rto * 2)
        if s.state == "SYN_SENT":
            self._tcp_send(s, SYN, seq=s.iss, mss=MSS)
        elif s.state == "SYN_RCVD":
            self._tcp_send(s, SYN | ACK, seq=s.iss, mss=MSS)
        else:
            # se reenvía lo que está en vuelo (desde el primer byte sin confirmar)
            in_flight = (s.snd_nxt - s.snd_una) & 0xFFFFFFFF
            if s.fin_sent:
                in_flight -= 1
            off = 0
            while off < in_flight:
                n = min(in_flight - off, s.peer_mss)
                self._tcp_send(s, ACK | PSH, bytes(s.sndbuf[off:off + n]),
                               seq=(s.snd_una + off) & 0xFFFFFFFF)
                off += n
            if in_flight == 0 and s.sndbuf and not s.fin_sent:
                # ventana cero del otro extremo: sonda de 1 byte
                self._tcp_send(s, ACK, bytes(s.sndbuf[:1]), seq=s.snd_una)
                s.snd_nxt = (s.snd_una + 1) & 0xFFFFFFFF
            if s.fin_sent:
                self._tcp_send(s, FIN | ACK, seq=s.fin_seq)
        self._arm(s)

    # ================================================================ DHCP
    def dhcp_start(self):
        xid = self.rand() & 0xFFFFFFFF
        self.dhcp = {"state": "DISCOVER", "xid": xid, "next": 0.0, "tries": 0, "offer": None}
        self.method = "dhcp"

    def _dhcp_packet(self, msgtype, extra=b""):
        d = self.dhcp
        hdr = struct.pack("!BBBBIHH4s4s4s4s", 1, 1, 6, 0, d["xid"], 0, 0x8000,
                          ZERO_IP, ZERO_IP, ZERO_IP, ZERO_IP)
        hdr += self.mac + b"\x00" * 10 + b"\x00" * 192 + b"\x63\x82\x53\x63"
        opts = bytes([53, 1, msgtype]) + extra + bytes([55, 4, 1, 3, 6, 51, 61, 7, 1]) + self.mac
        opts += bytes([12, 4]) + b"pyos" + b"\xff"
        return hdr + opts

    def _dhcp_send(self, msgtype, extra=b""):
        pkt = self._dhcp_packet(msgtype, extra)
        self._send_ip(BCAST_IP, PROTO_UDP, udp(ZERO_IP, BCAST_IP, 68, 67, pkt), src=ZERO_IP)

    def _dhcp_tick(self, now):
        d = self.dhcp
        if d["state"] == "BOUND":
            # renovación (RFC 2131, T1 = mitad de la concesión): se pide la misma IP
            if d.get("renew_at") is not None and now >= d["renew_at"]:
                d.update(state="REQUEST", tries=0, next=0.0, renewing=True,
                         offer={"ip": self.ip, "server": d.get("server", ZERO_IP)})
                self.log("net: renovando la concesión DHCP de %s" % ip2s(self.ip))
            else:
                return
        if d["state"] == "FAILED" or now < d["next"]:
            return
        d["tries"] += 1
        if d.get("renewing") and d["tries"] > 4:
            # el servidor no contesta: se mantiene la IP hasta que caduque la concesión
            d.update(state="BOUND", renewing=False)
            left = d["expire"] - now
            if left <= 0:
                d.update(state="DISCOVER", tries=0, next=0.0, renew_at=None)
                self.log("net: la concesión DHCP ha caducado", "warn")
            else:
                d["renew_at"] = now + max(30.0, left / 2)
            return
        if d["tries"] > 8:
            d["state"] = "FAILED"
            self.log("net: DHCP sin respuesta; configura la red con 'ifconfig ip ...'", "warn")
            self.cfg_wq.wake_all()
            return
        d["next"] = now + min(8.0, 1.0 * d["tries"])
        if d["state"] == "DISCOVER":
            self._dhcp_send(1)
        elif d["state"] == "REQUEST":
            o = d["offer"]
            self._dhcp_send(3, bytes([50, 4]) + o["ip"] + bytes([54, 4]) + o["server"])

    def _dhcp_in(self, data):
        d = self.dhcp
        if len(data) < 240 or data[0] != 2 or struct.unpack("!I", data[4:8])[0] != d["xid"]:
            return
        if data[236:240] != b"\x63\x82\x53\x63":
            return
        yiaddr = data[16:20]
        opts = {}
        i = 240
        while i < len(data):
            k = data[i]
            if k == 255:
                break
            if k == 0:
                i += 1
                continue
            if i + 1 >= len(data):
                break
            ln = data[i + 1]
            opts[k] = data[i + 2:i + 2 + ln]
            i += 2 + ln
        mt = opts.get(53, b"\x00")[0]
        if mt == 2 and d["state"] == "DISCOVER":
            d["offer"] = {"ip": yiaddr, "server": opts.get(54, data[20:24])[:4]}
            d["state"] = "REQUEST"
            d["tries"] = 0
            d["next"] = 0.0
            self._dhcp_tick(self.clock())
        elif mt == 5 and d["state"] == "REQUEST":
            mask = opts.get(1, b"\xff\xff\xff\x00")[:4]
            gw = opts.get(3, ZERO_IP)[:4]
            dns = opts.get(6, gw)[:4]
            lease = struct.unpack("!I", opts[51][:4])[0] if 51 in opts else 0
            now = self.clock()
            renewing = d.get("renewing")
            d.update(state="BOUND", lease=lease, renewing=False,
                     server=opts.get(54, d["offer"]["server"])[:4],
                     expire=now + lease if lease else None,
                     renew_at=now + lease / 2.0 if 0 < lease < 0xFFFFFFFF else None)
            if not (renewing and yiaddr == self.ip and self.configured):
                self.configure(yiaddr, mask, gw, dns, "dhcp")
        elif mt == 6 and d["state"] == "REQUEST":
            d["state"] = "DISCOVER"
            d["renewing"] = False
            d["tries"] = 0
            d["next"] = 0.0

    # ================================================================ DNS
    def _dns_ports(self):
        return set(q["port"] for q in self.dns_q.values())

    def resolve_start(self, name):
        """Inicia la resolución; devuelve el objeto consulta (con wq, done, result)."""
        name = name.strip().rstrip(".").lower()
        q = {"name": name, "done": False, "result": [], "tries": 1, "wq": self.make_wq("dns")}
        if name == "localhost":
            q.update(done=True, result=[b"\x7f\x00\x00\x01"])
            return q
        c = self.dns_cache.get(name)
        if c is not None and c[1] > self.clock():
            q.update(done=True, result=c[0])
            return q
        if not self.configured or self.dns == ZERO_IP:
            q.update(done=True, result=[], error=EHOSTUNREACH)
            return q
        qid = self.rand() & 0xFFFF
        while qid in self.dns_q:
            qid = (qid + 1) & 0xFFFF
        q["port"] = self.alloc_port()
        self.udp_ports[q["port"]] = None          # reservado
        q["deadline"] = self.clock() + 2.0
        self.dns_q[qid] = q
        self._dns_send(qid, q)
        return q

    def _dns_send(self, qid, q):
        msg = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
        for label in q["name"].split("."):
            lb = label.encode("idna" if any(ord(c) > 127 for c in label) else "ascii")
            msg += bytes([len(lb)]) + lb
        msg += b"\x00" + struct.pack("!HH", 1, 1)
        self._send_ip(self.dns, PROTO_UDP, udp(self.ip, self.dns, q["port"], 53, msg))

    def _dns_in(self, port, data):
        if len(data) < 12:
            return
        qid, fl, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
        q = self.dns_q.get(qid)
        if q is None or q["port"] != port:
            return
        i = 12
        for _ in range(qd):
            i = _skip_name(data, i) + 4
        out = []
        ttl_min = 3600
        for _ in range(an):
            i = _skip_name(data, i)
            if i + 10 > len(data):
                break
            typ, cls, ttl, ln = struct.unpack("!HHIH", data[i:i + 10])
            i += 10
            if typ == 1 and cls == 1 and ln == 4:
                out.append(data[i:i + 4])
                ttl_min = min(ttl_min, ttl)
            i += ln
        del self.dns_q[qid]
        self.udp_ports.pop(port, None)
        q["result"] = out
        q["done"] = True
        if fl & 0x000F == 3:
            q["error"] = "NXDOMAIN"
        if out:
            self.dns_cache[q["name"]] = (out, self.clock() + max(5, ttl_min))
        q["wq"].wake_all()


def _skip_name(data, i):
    while i < len(data):
        ln = data[i]
        if ln == 0:
            return i + 1
        if ln & 0xC0 == 0xC0:
            return i + 2
        i += 1 + ln
    return i
