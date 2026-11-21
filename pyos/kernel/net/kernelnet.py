"""Red en el kernel: une la pila TCP/IP con los procesos (sockets como ficheros)."""
from ..errors import KError, EAGAIN, EBADF, EINTR, EINVAL, ENODEV
from ..fs.vfs import FileOps, O_NONBLOCK
from ..proc.process import Block, WaitQueue
from .pkt import ip2s, s2ip
from .stack import NetStack, Socket, ZERO_IP

ENOTCONN, EISCONN, EDESTADDRREQ = 107, 106, 89


def _ip(s):
    try:
        return s2ip(s)
    except (ValueError, TypeError):
        raise KError(EINVAL, "dirección IPv4 inválida: %r" % (s,))


class SocketFile(FileOps):
    seekable = False

    def __init__(self, net, sock):
        self.net = net
        self.s = sock

    def _wait(self, of):
        p = self.net.k.current
        if of.flags & O_NONBLOCK:
            raise KError(EAGAIN)
        if p.pending_signals:
            raise KError(EINTR)
        raise Block(self.s.wq)

    def read(self, of, n):
        s = self.s
        if s.kind == "udp":
            if s.dgrams:
                return s.dgrams.pop(0)[0][:n]
            return self._wait(of)
        if s.rcvbuf:
            data = bytes(s.rcvbuf[:n])
            del s.rcvbuf[:len(data)]
            self.net.stack._tcp_output(s)          # la ventana se abrió
            return data
        if s.peer_fin or s.state in ("CLOSED", "TIME_WAIT", "LAST_ACK", "CLOSING"):
            if s.error and s.state == "CLOSED":
                raise KError(s.error)
            return b""
        if s.state in ("SYN_SENT", "SYN_RCVD", "ESTABLISHED", "FIN_WAIT_1", "FIN_WAIT_2"):
            return self._wait(of)
        raise KError(ENOTCONN)

    def write(self, of, data):
        s = self.s
        if s.kind == "udp":
            if s.raddr is None:
                raise KError(EDESTADDRREQ)
            return self.net.sendto(s, data, s.raddr)
        if s.state in ("SYN_SENT", "SYN_RCVD"):
            return self._wait(of)
        try:
            n = self.net.stack.tcp_send(s, data)
        except OSError as e:
            raise KError(e.args[0], e.args[1] if len(e.args) > 1 else "")
        if n == 0:
            return self._wait(of)
        return n

    def close(self, of):
        self.net.close(self.s)


class NullNIC(object):
    """Sin tarjeta de red: solo existe la interfaz de bucle local (127.0.0.1)."""
    desc = "sin tarjeta (solo loopback)"
    mac = b"\x00" * 6
    present = False

    def send(self, frame):
        pass

    def poll(self):
        return []

    def link_up(self):
        return False


class KernelNet(object):
    def __init__(self, kernel, nic, cmdline):
        self.k = kernel
        self.nic = nic
        rnd = kernel.m.random_bytes if hasattr(kernel.m, "random_bytes") else None

        def rand():
            if rnd is not None:
                return int.from_bytes(rnd(4), "little")
            import random
            return random.getrandbits(32)
        self.stack = NetStack(nic, kernel.clock, log=kernel.log,
                              make_wq=lambda name: WaitQueue(kernel, name), rand=rand)
        self.pending = []
        self.ticks = 0
        mode = cmdline.get("net", "dhcp") if getattr(nic, "present", True) else "off"
        if mode.startswith("ip="):
            mode = mode[3:]
        if mode == "dhcp":
            self.stack.dhcp_start()
        elif mode != "off":
            self.config_static(mode)
        kernel.log("net: %s, MAC %s, enlace %s" % (
            getattr(nic, "desc", "NIC"), ":".join("%02x" % b for b in nic.mac),
            "activo" if getattr(nic, "link_up", lambda: True)() else "caído"))

    def config_static(self, spec):
        """ip/prefijo,puerta,dns  p. ej. 10.0.2.15/24,10.0.2.2,10.0.2.3"""
        parts = spec.split(",")
        ip, _, pre = parts[0].partition("/")
        pre = int(pre or 24)
        mask = (0xFFFFFFFF << (32 - pre)) & 0xFFFFFFFF
        gw = parts[1] if len(parts) > 1 else "0.0.0.0"
        dns = parts[2] if len(parts) > 2 else gw
        self.stack.dhcp = None
        self.stack.configure(_ip(ip), mask.to_bytes(4, "big"), _ip(gw), _ip(dns), "estática")

    # --- interrupción y reloj
    def irq_pending(self):
        frames = self.nic.poll()
        if frames:
            self.pending.extend(frames)
        return bool(self.pending or self.stack.loop_q)

    def interrupt(self):
        frames, self.pending = self.pending, []
        for f in frames:
            self.stack.input(f)
        self.stack.loopback()

    def timer(self):
        self.ticks += 1
        if self.ticks % 5 == 0:                     # 20 Hz bastan para los temporizadores
            self.stack.tick()

    # --- operaciones para las syscalls
    def socket(self, p, kind):
        if kind not in ("tcp", "udp"):
            raise KError(EINVAL)
        s = Socket(self.stack, kind)
        return SocketFile(self, s)

    def sock_of(self, of):
        if not isinstance(of.ops, SocketFile):
            raise KError(EBADF, "no es un socket")
        return of.ops.s

    def connect(self, p, of, ip, port):
        s = self.sock_of(of)
        if s.kind == "udp":
            if not s.lport:
                self.stack.udp_bind(s, 0)
            s.raddr = (_ip(ip), port)
            return 0
        if s.state == "ESTABLISHED" or (s.state in ("CLOSE_WAIT",) and s.connecting):
            s.connecting = False
            return 0
        if s.state == "CLOSED" and s.connecting:
            s.connecting = False
            raise KError(s.error or 111)
        if s.state == "CLOSED":
            try:
                self.stack.tcp_connect(s, _ip(ip), port)
            except OSError as e:
                raise KError(e.args[0], e.args[1] if len(e.args) > 1 else "")
        if of.flags & O_NONBLOCK:
            raise KError(EAGAIN)
        if p.pending_signals:
            raise KError(EINTR)
        raise Block(s.wq)

    def bind(self, p, of, port):
        s = self.sock_of(of)
        try:
            if s.kind == "udp":
                self.stack.udp_bind(s, port)
            else:
                s.lport = port
        except OSError as e:
            raise KError(e.args[0], e.args[1])
        return 0

    def listen(self, p, of, backlog):
        s = self.sock_of(of)
        if s.kind != "tcp" or not s.lport:
            raise KError(EINVAL, "listen necesita un socket TCP con bind()")
        try:
            self.stack.tcp_listen(s, s.lport, backlog)
        except OSError as e:
            raise KError(e.args[0], e.args[1])
        return 0

    def accept(self, p, of):
        s = self.sock_of(of)
        if s.state != "LISTEN":
            raise KError(EINVAL)
        if s.backlog:
            c = s.backlog.pop(0)
            c.parent = None
            return SocketFile(self, c), (ip2s(c.raddr[0]), c.raddr[1])
        if of.flags & O_NONBLOCK:
            raise KError(EAGAIN)
        if p.pending_signals:
            raise KError(EINTR)
        raise Block(s.wq)

    def sendto(self, s, data, addr):
        try:
            return self.stack.udp_sendto(s, data, addr)
        except OSError as e:
            raise KError(e.args[0], e.args[1] if len(e.args) > 1 else "")

    def recvfrom(self, p, of, n):
        s = self.sock_of(of)
        if s.kind != "udp":
            raise KError(EINVAL)
        if s.dgrams:
            data, (ip, port) = s.dgrams.pop(0)
            return (data[:n], ip2s(ip), port)
        of.ops._wait(of)

    def close(self, s):
        if s.kind == "udp":
            if s.lport and self.stack.udp_ports.get(s.lport) is s:
                del self.stack.udp_ports[s.lport]
            s.state = "CLOSED"
        else:
            self.stack.tcp_close(s)

    def ping(self, p, ip, ident, seq, timeout_ms):
        st = self.stack
        rtt = st.ping_result(ident, seq)
        if rtt is not None:
            st.ping_forget(ident, seq)
            p.deadline = None
            return rtt * 1000.0
        now = self.k.clock()
        if p.deadline is None:
            dst = _ip(ip)
            if not st.configured and dst[0] != 127:
                raise KError(113, "red sin configurar")
            p.deadline = now + timeout_ms / 1000.0
            wq = st.ping_send(dst, ident, seq)
        elif now >= p.deadline:
            p.deadline = None
            st.ping_forget(ident, seq)
            return None
        else:
            wq = st.pings[(ident, seq)][2]
        if p.pending_signals:
            p.deadline = None
            st.ping_forget(ident, seq)
            raise KError(EINTR)
        raise Block(wq, p.deadline)

    def resolve(self, p, name):
        q = getattr(p, "dns_query", None)
        if q is None or q["name"] != name.strip().rstrip(".").lower():
            q = self.stack.resolve_start(name)
            p.dns_query = q
        if q["done"]:
            p.dns_query = None
            if q.get("error") == 113:
                raise KError(113, "red sin configurar")
            return [ip2s(x) for x in q["result"]]
        if p.pending_signals:
            p.dns_query = None
            raise KError(EINTR)
        raise Block(q["wq"])

    def info(self):
        i = self.stack.info()
        i["available"] = True
        i["nic"] = getattr(self.nic, "present", True)
        i["reason"] = getattr(self.k.m, "nic_error", "") or "no hay tarjeta de red soportada"
        return i

    def proc_text(self):
        st = self.stack
        i = st.info()
        lines = ["interfaz  net0 (%s)" % i["driver"],
                 "mac       %s" % i["mac"],
                 "ipv4      %s/%s  [%s]" % (i["ip"], i["mask"], i["method"]),
                 "puerta    %s" % i["gw"],
                 "dns       %s" % i["dns"],
                 "dhcp      %s" % i["dhcp"],
                 "enlace    %s" % ("activo" if i["link"] else "caído"),
                 "tramas    rx %(rx)d (%(rx_bytes)d B)  tx %(tx)d (%(tx_bytes)d B)  descartadas %(drop)d" % i["stats"],
                 "", "ARP:"]
        for ip, (mac, exp) in sorted(st.arp.items()):
            lines.append("  %-15s %s" % (ip2s(ip), ":".join("%02x" % b for b in mac)))
        lines += ["", "SOCKETS:"]
        for port, s in sorted(st.udp_ports.items()):
            if s is not None:
                lines.append("  " + s.describe())
        for port, s in sorted(st.listeners.items()):
            lines.append("  " + s.describe())
        for s in st.tcp_conns.values():
            lines.append("  " + s.describe())
        return "\n".join(lines) + "\n"
