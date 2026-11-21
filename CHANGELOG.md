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
