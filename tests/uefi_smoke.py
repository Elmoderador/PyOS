"""Prueba de humo de la imagen UEFI en QEMU+OVMF (sin Linux). No forma parte de pytest.

    python tests/uefi_smoke.py build/uefi/pyos-uefi.img [disco-linux.img]

Arranca la imagen, teclea órdenes por la UART, prueba el teclado PS/2 con
pulsaciones del monitor de QEMU y apaga con el botón de encendido ACPI.
Arranques: 1) selector -> Term por la UART; órdenes, PS/2, ACPI. 2) selector -> LOOK
con el teclado PS/2 (cae a Term porque LOOK no está instalado) y persistencia.
3) si se da un segundo disco con una distribución, el selector debe listarla y
el chainload debe arrancar su kernel Linux real.
"""
import codecs
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

IMG = sys.argv[1] if len(sys.argv) > 1 else "build/uefi/pyos-uefi.img"
OUTDIR = os.environ.get("PYOS_SMOKE_OUT", "build/uefi")


def read_ppm(path):
    data = open(path, "rb").read()
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    pix = parts[3]

    def px(x, y):
        o = (y * w + x) * 3
        return tuple(pix[o:o + 3])
    return w, h, px
LINUX_DISK = sys.argv[2] if len(sys.argv) > 2 else None
OVMF = "/usr/share/OVMF/OVMF_CODE_4M.fd"
VARS = "/usr/share/OVMF/OVMF_VARS_4M.fd"
STRIP = re.compile(rb"\x1b\[[0-9;?=]*[A-Za-z]")


class VM(object):
    def __init__(self, disk, workdir, extra_disk=None):
        self.ser = os.path.join(workdir, "ser.sock")
        self.mon = os.path.join(workdir, "mon.sock")
        vars_ = os.path.join(workdir, "vars.fd")
        if not os.path.exists(vars_):
            shutil.copy(VARS, vars_)
        cmd = ["qemu-system-x86_64", "-m", "512", "-display", "none", "-nic", "user,model=e1000",
               "-drive", "if=pflash,format=raw,readonly=on,file=" + OVMF,
               "-drive", "if=pflash,format=raw,file=" + vars_,
               "-drive", "file=%s,format=raw" % disk,
               ] + (["-drive", "file=%s,format=raw,snapshot=on" % extra_disk] if extra_disk else []) + [
               "-chardev", "socket,id=s0,path=%s,server=on,wait=off" % self.ser,
               "-serial", "chardev:s0", "-monitor", "unix:%s,server,nowait" % self.mon]
        if os.path.exists("/dev/kvm"):
            cmd += ["-enable-kvm"]
        self.p = subprocess.Popen(cmd)
        for _ in range(100):
            try:
                self.s = socket.socket(socket.AF_UNIX)
                self.s.connect(self.ser)
                break
            except OSError:
                time.sleep(0.1)
        self.s.settimeout(0.5)
        self.buf = b""
        self.log = b""
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")

    def expect(self, token, timeout=600):
        end = time.time() + timeout
        tok = token.encode() if isinstance(token, str) else token
        while time.time() < end:
            try:
                c = self.s.recv(65536)
                if not c:
                    break
                c = STRIP.sub(b"", c).replace(b"\r", b"")
                self.buf += c
                self.log += c
                sys.stdout.write(self.dec.decode(c))
                sys.stdout.flush()
            except socket.timeout:
                pass
            i = self.buf.find(tok)
            if i >= 0:
                self.buf = self.buf[i + len(tok):]
                return True
            if self.p.poll() is not None:
                break
        raise TimeoutError("no apareció %r" % token)

    def send_raw(self, data):
        self.s.send(data)

    def send(self, line):
        for ch in line.encode("utf-8") + b"\r":
            self.s.send(bytes([ch]))
            time.sleep(0.02)

    def monitor(self, cmd):
        m = socket.socket(socket.AF_UNIX)
        m.connect(self.mon)
        m.recv(4096)
        m.send((cmd + "\n").encode())
        time.sleep(0.3)
        m.close()

    def pause(self, secs):
        """Espera leyendo la consola serie (para que el registro no se pierda)."""
        try:
            self.expect("\x00NUNCA\x00", secs)
        except TimeoutError:
            pass

    def sendkeys(self, text):
        keys = {" ": "spc", "-": "slash", ".": "dot", "/": "shift-7", "\n": "ret", ">": "shift-less"}
        for ch in text:
            self.monitor("sendkey " + keys.get(ch, ch))
            time.sleep(0.15)

    def wait_exit(self, timeout=180):
        return self.p.wait(timeout)


def main():
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        disk = os.path.join(d, "disk.img")
        shutil.copy(IMG, disk)
        vm = VM(disk, d)
        vm.expect("Esperando tu elecci")
        print("\n=== selector tras %.0f s ===" % (time.time() - t0))
        vm.send_raw(b"2")                      # PyOS Term, por la UART
        vm.expect("Modo de arranque: PyOS Term")
        vm.expect("root@pyos:/root# ")
        print("\n=== shell tras %.0f s ===" % (time.time() - t0))
        for cmd in ["hwinfo", "cat /proc/cpuinfo", "echo persistencia-uefi > /root/u.txt",
                    "pkg install juegos", "svc list", "dev kbd us", "dev kbd es", "pyos", "lx",
                    "ifconfig", "ping -c 2 10.0.2.2", "svc start httpd", "wget http://127.0.0.1/estado -O /root/e.html",
                    "forktest", "sandbox", "python -c print(6*7)", "spin 2 &", "echo shell-viva", "top", "memtest"]:
            vm.send(cmd)
            vm.expect("root@pyos:/root# ", 900)
        vm.sendkeys("uname\n")                 # teclado PS/2 real (driver de PyOS)
        vm.expect("PyOS", 300)
        vm.expect("root@pyos:/root# ", 300)
        vm.monitor("system_powerdown")         # botón de encendido ACPI
        vm.expect("Sistema detenido", 300)
        rc = vm.wait_exit()
        log = vm.log.decode("utf-8", "replace")
        assert "ACPI PM timer" in log and "PVM íntegra" in log and "soy el hijo tras exec()" in log
        assert "acpi: botón de encendido pulsado" in log, "ACPI power button"
        assert "instalado juegos 1.0" in log and "activo:" in log
        assert "distribución 'us'" in log and "no hay kernel Linux" in log
        assert "inet 10.0.2.15" in log and "2 enviados, 2 recibidos" in log and "HTTP 200" in log
        print("\n=== primer arranque OK (%.0f s), QEMU rc=%s ===" % (time.time() - t0, rc))
        vm = VM(disk, d)
        vm.expect("Esperando tu elecci")
        vm.sendkeys("1")                       # PyOS LOOK, con el teclado PS/2 (firmware -> selector)
        vm.expect("gfx: pantalla para", 600)
        vm.pause(20)
        shot = os.path.join(d, "look.ppm")
        vm.monitor("screendump " + shot)
        vm.pause(2)
        w, h, px = read_ppm(shot)
        assert px(90, h - 8) == (0x10, 0xB9, 0x81), "LOOK no dibujó la barra de tareas"
        # ratón PS/2 relativo: del centro al icono Terminal (52, 52), doble clic
        x, y = w // 2, h // 2
        while (x, y) != (52, 52):
            dx, dy = max(-5, min(5, 52 - x)), max(-5, min(5, 52 - y))
            vm.monitor("mouse_move %d %d" % (dx, dy))
            x, y = x + dx, y + dy
        vm.pause(3)
        for _ in range(2):
            vm.monitor("mouse_button 1")
            vm.monitor("mouse_button 0")
        vm.pause(45)
        vm.sendkeys("echo look-uefi > /root/lu.txt")
        vm.monitor("sendkey ret")
        vm.pause(30)
        vm.monitor("screendump " + os.path.join(OUTDIR, "look-uefi.ppm"))
        vm.monitor("sendkey f1")               # menú PyOS -> "Salir a PyOS Term"
        vm.pause(8)
        for k in ("up", "up", "up", "ret"):
            vm.monitor("sendkey " + k)
            vm.pause(2)
        vm.expect("has salido de PyOS LOOK", 600)
        vm.expect("root@pyos:/root# ")
        print("\n=== LOOK en UEFI OK (%.0f s) ===" % (time.time() - t0))
        for cmd in ["cat /root/u.txt", "cat /root/lu.txt", "pkg list", "tresenraya"]:
            vm.send(cmd)
            if cmd == "tresenraya":
                vm.expect("> ", 300)
                vm.send_raw(b"\x04")
            vm.expect("root@pyos:/root# ", 300)
        log = vm.log.decode("utf-8", "replace")
        assert "persistencia-uefi" in log and "juegos" in log and "Tú eres X" in log
        assert "\nlook-uefi" in log.replace("\r", ""), "el terminal de LOOK no ejecutó la orden"
        vm.send("halt")
        vm.expect("Sistema detenido", 300)
        vm.wait_exit()
        print("\n=== segundo arranque OK (%.0f s) ===" % (time.time() - t0))
        if LINUX_DISK:
            vm = VM(disk, d, LINUX_DISK)
            vm.expect("Esperando tu elecci")
            log = vm.log.decode("utf-8", "replace")
            m = re.search(r"(\d)\. (Alpine Linux|Ubuntu|Arch Linux|Kali Linux|Debian)", log)
            assert m, "el selector no listó la distribución del segundo disco"
            vm.send_raw(m.group(1).encode())
            vm.expect("Linux version", 900)
            print("\n=== chainload a %s OK (%.0f s) ===" % (m.group(2), time.time() - t0))
            vm.p.kill()
        print("\n=== UEFI SMOKE TEST OK (%.0f s) ===" % (time.time() - t0))


if __name__ == "__main__":
    main()
