# Changelog

## Versionado: U.P.S. (Update.Patch.Security)

Cada versión de PyOS es `U.P.S`:

| Número | Sube cuando… | Al subir… |
|---|---|---|
| **U** (Update) | hay funciones nuevas o cambios de comportamiento | P y S vuelven a 0 |
| **P** (Patch) | se arreglan fallos, sin funciones nuevas | S vuelve a 0 |
| **S** (Security) | **solo** arreglos de seguridad | — |

Ejemplos: `1.0.0` → `1.0.1` (arreglo de seguridad) → `1.1.0` (arreglo de fallos) → `2.0.0`
(funciones nuevas). Una versión que lleve funciones nuevas y arreglos sube U.

**Compatibilidad.** U.P.S. no dice por sí solo si algo deja de funcionar, así que las interfaces
de las que dependen otros llevan su propio número:

- `LOOK_API` (en `pyos/packages/look/lib/look/core.py`): la API de aplicaciones de terceros de
  LOOK (`Window`, `LOOK_APPS`, órdenes de dibujo, eventos).
- Las syscalls (`pyos/kernel/syscalls.py`): un número de syscall nunca se reutiliza para otra cosa.

Cuando una versión rompe alguna de ellas, su entrada empieza con **⚠ Cambio incompatible** y
dice qué hay que cambiar.

Las versiones se etiquetan en Git como `vU.P.S` y cada una tiene su Release con las imágenes de disco.

---

## 1.0.1 — 2026-11-21 · Security

Solo arreglos de seguridad, encontrados en una auditoría con fuzzers (red, syscalls, interfaz)
y revisión manual. Sin funciones nuevas; `LOOK_API` sigue en 1 y ninguna syscall cambia de
significado (se añaden constantes de errno a libpy).

### Red (remoto)
- **Cuelgue del kernel con un SYN.** Un MSS de 0 en las opciones TCP dejaba el bucle de envío
  troceando en segmentos de 0 bytes para siempre. Ahora el MSS se acota a [88, 1460].
- **Caída del kernel con DHCP.** La opción 53 vacía lanzaba `IndexError` durante el arranque;
  un servidor DHCP falso en la red local bastaba. Las opciones de direcciones más cortas de
  4 bytes se descartan y la concesión exige 4 bytes.
- TCP con *data offset* imposible (menor que 20 o mayor que el segmento) se descarta.
- DNS: un registro A truncado ya no entra en el resultado como una dirección de 2 bytes.
- **Defensa en profundidad:** una trama que haga fallar a la pila se descarta y se registra, y
  un fallo en el manejador de cualquier IRQ se registra sin tumbar el kernel (`KernelPanic`
  sigue deteniéndolo).

### PVM (aislamiento)
- **Lectura de memoria del anfitrión con `str.format`.** `'{0.__class__.__init__.__globals__}'`
  recorría atributos en C sin pasar por el filtro de la PVM. Ahora `str.format` usa un
  formateador que valida cada atributo, incluidos los campos anidados.

### Servicios
- `httpd`: XSS reflejado en la página 404 (la ruta se escapa); rutas sin `/` inicial leían
  ficheros hermanos de `/var/www`; plazos de 10 s para recibir la petición y 20 s para enviarla
  (antes, un cliente callado bloqueaba el servidor para siempre).
- `pkg`: el nombre del paquete se usaba como ruta (`../../sbin/init.py` sobrescribía ficheros
  protegidos); un paquete ya no puede pisar ficheros que no sean suyos (como dpkg), ni tocar
  `/var/pkg/`, `/boot/`, `/proc/` o `/dev/`; tamaños negativos (bucle infinito) y
  dependencias con nombres no válidos se rechazan.
- `klog`: el texto se sanea (sin control, ESC ni sustitutos sueltos); un sustituto suelto
  dejaba `dmesg` roto para todos y ESC permitía secuencias ANSI y líneas falsas.

### Otros
- El banner de `/etc/motd` aún decía "PyOS 2.1"; ya no lleva número de versión.
- Nuevos: `tests/netfuzz.py`, `tests/sysfuzz.py`, `tests/test_netsec.py`, `tests/test_sec.py`.

---

## 1.0.0 — 2026-11-21

Primera versión pública. Reúne todo el trabajo anterior a la publicación (las numeraciones
internas previas, como "kernel 2.1.0" o "LOOK 1.1", desaparecen: todo pasa a ser 1.0.0).

### Kernel
- Kernel escrito solo en Python: procesos, planificador, memoria, señales, tuberías, VFS
  con PyFS (sistema de archivos propio con diario), procfs y devfs.
- PVM: CPU virtual con bytecode propio compilado desde el AST de Python, superinstrucciones
  y aislamiento de los programas de usuario.
- Arranque real en UEFI sobre CPython 3.6.8 (edk2-libc), en QEMU, VirtualBox y VMware.
- Drivers en Python: consola UEFI con ANSI, teclado PS/2 con distribuciones, ratón PS/2
  con rueda (IntelliMouse), framebuffer Bochs/VBE, disco, Intel e1000.
- Red: ARP, IPv4, ICMP, UDP, TCP, DHCP (con renovación), DNS y loopback, en Python.
- Subsistema Linux: selector de arranque y chainload de una distribución instalada.
- Syscalls `exctb` (traza de una excepción) y `klog` (escribir en el log del kernel).

### Userland
- PyOS Term: shell, servicios (`svc`), paquetes (`pkg`), herramientas de red
  (`ifconfig`, `ping`, `nslookup`, `wget`, `nc`), servidor web `httpd`.
- Arcade: 8 juegos de terminal.

### PyOS LOOK (entorno gráfico)
- Escritorio, ventanas, barra de tareas, menús, temas (incluido alto contraste), fondo con imagen.
- Aplicaciones: Terminal, Archivos, Notas, Procesos, Navegador, Paint, Imágenes, Calculadora,
  Calendario, Aplicaciones, Ajustes, Juegos (Buscaminas, Serpiente), Ayuda.
- Portapapeles, menús contextuales, encaje de ventanas, avisos, aplicaciones de terceros
  (`/usr/share/look/apps`, `LOOK_API = 1`) y fallos aislados por aplicación.
- Optimizado para framebuffers lentos (oclusión, repintado parcial, movimiento con contorno).
