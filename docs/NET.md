# Red en PyOS

Todo es Python: el driver de la tarjeta, la pila TCP/IP, los sockets y los programas.
El firmware no participa: PyOS desconecta el driver de red UEFI (iPXE/MNP) antes de
tocar la tarjeta.

```
programas (wget, nc, ping, httpd, Navegador de LOOK)       userland, PVM
   │ syscalls 64–74 (socket, connect, accept, sendto…)
KernelNet: sockets como ficheros (read/write/close/poll)    kernel/net/kernelnet.py
NetStack: ARP · IPv4 · ICMP · UDP · TCP · DHCP · DNS · lo    kernel/net/stack.py
E1000: anillos DMA en RAM física, MMIO por BAR0             hal/uefi_net.py
Intel 82540EM (e1000) ─────────────────────────────────────  hardware de la VM
```

## Configurar la VM

| Hipervisor | Tarjeta |
|---|---|
| VirtualBox | **Intel PRO/1000 MT Desktop (82540EM)**, conectada a **NAT** |
| QEMU | `-nic user,model=e1000` |
| VMware | `ethernet0.virtualDev = "e1000"` |
| Hyper-V | no soportada (solo tiene tarjeta sintética) |

VirtualBox por PowerShell, con la VM apagada:
```powershell
& $vb modifyvm PyOS2 --nic1 nat --nictype1 82540EM
# opcional: ver el httpd de PyOS desde el navegador de Windows en http://localhost:8080
& $vb modifyvm PyOS2 --natpf1 "web,tcp,,8080,,80"
```

Ids PCI soportados: 8086:100E, 100F, 1004, 100C, 10D3. Con otra tarjeta (o sin ninguna)
PyOS arranca igual con solo `lo` (127.0.0.1).

## Arranque

Por defecto pide dirección por **DHCP**. En la línea de comandos del kernel:
- `net=off`: sin red (solo loopback).
- `net=10.0.2.15/24,10.0.2.2,10.0.2.3`: IP estática, puerta de enlace y DNS.

## Programas

| Orden | Qué hace |
|---|---|
| `ifconfig` | interfaces, MAC, IP, puerta de enlace, DNS, contadores |
| `ping [-c N] host` | ICMP echo con tiempos |
| `nslookup nombre` | resolución DNS (A) |
| `wget URL [-O fichero]` | descarga HTTP/1.0 con redirecciones |
| `nc host puerto`, `nc -l puerto` | cliente/servidor TCP de línea |
| `svc start httpd` | servidor web: sirve `/var/www` y `/estado` (estado del sistema en vivo) |
| Navegador (LOOK) | HTML básico: títulos, párrafos, listas, negrita, enlaces, `<pre>`, entidades; historial, barra de dirección |

`/proc/net` muestra la configuración y los sockets abiertos.

## Qué hay implementado

- **ARP** con caché y cola de paquetes pendientes (3 reintentos).
- **IPv4** con enrutado a la puerta de enlace; descarta fragmentos (no reensambla).
- **ICMP** echo request/reply (PyOS responde a ping).
- **UDP** con sockets `sendto`/`recvfrom`.
- **TCP**: apertura activa y pasiva, backlog de `listen`, cierre ordenado y TIME_WAIT,
  RST, retransmisión go-back-N con RTO exponencial (1–16 s), sonda de ventana cero,
  MSS 1460. Recepción solo en orden (lo que llega desordenado se descarta y se
  reconoce el último byte en orden, lo que provoca la retransmisión del emisor).
- **DHCP** (DISCOVER/OFFER/REQUEST/ACK). Renueva a mitad de la concesión; si el servidor
  no contesta conserva la IP hasta que caduca y entonces vuelve a empezar.
- **DNS** sobre UDP con caché que respeta el TTL.
- **Loopback** 127.0.0.0/8 completo (TCP y UDP), funciona sin tarjeta.

## Límites

- Sin TLS: `https://` no funciona. La mayoría de webs públicas redirigen a HTTPS;
  `http://neverssl.com` y `http://example.com` sirven para probar.
- Sin IPv6, sin reensamblado de fragmentos, sin SACK ni control de congestión
  (ventana fija), sin opciones TCP salvo MSS.
- La tarjeta se sondea (no hay interrupciones reales, igual que el resto de
  dispositivos de PyOS). La latencia depende del cuanto del planificador: en QEMU
  TCG, ping a la puerta de enlace ~3 ms.
- El rendimiento lo marca Python: decenas o pocos cientos de KiB/s según la VM.
- El Navegador no ejecuta JavaScript ni aplica CSS, y no muestra imágenes (sí su `alt`).
  La carga de una página bloquea LOOK hasta que termina.

## Probado

- Tests en el host con una red simulada (`tests/netsim.py`: router con ARP, DHCP,
  DNS y servidor TCP con pérdidas): `tests/test_net.py`, `tests/test_netsys.py`.
- En UEFI real (QEMU + OVMF + e1000 + slirp), dentro de `tests/uefi_smoke.py`: DHCP
  (10.0.2.15), ping a 10.0.2.2, httpd + wget por loopback; a mano: DNS de example.com,
  wget desde un servidor del host y el host descargando de PyOS por `hostfwd`.
