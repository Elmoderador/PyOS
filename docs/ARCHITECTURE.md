# PyOS — Dual Kernel & Dual Execution

Este documento describe qué hay **implementado y probado**, qué es **experimental**
y qué **no es posible** con esta arquitectura, con el motivo técnico.

## 1. Vista general

```
                    Firmware UEFI (OVMF / VirtualBox EFI / Hyper-V Gen2)
                                       │
                          UEFI Shell ─► Python.efi ─► start.py
                                       │
                         ┌──── Selector de arranque PyOS ────┐
                         │ 1. PyOS LOOK   2. PyOS Term       │
                         │ 3+. distribuciones detectadas     │
                         └──────┬───────────────┬────────────┘
                 kernel PyOS    │               │  chainload del cargador EFI
             (mode=look|term)   │               │  de la distro (shim/GRUB/systemd-boot)
                                ▼               ▼
                 ┌─────────────────────┐   ┌──────────────────────────────┐
                 │ PyOS nativo         │   │ Kernel Linux real            │
                 │ procesos PVM        │   │  └─ (opcional) PyOS alojado: │
                 │ sin apps Linux      │   │     python3 -m pyos run      │
                 └─────────────────────┘   │       --linux                │
                                           │     procesos PVM + procesos  │
                                           │     Linux reales (lx)        │
                                           └──────────────────────────────┘
```

Dos kernels **independientes**, uno cada vez, elegidos en el arranque. El kernel PyOS
no se modifica ni depende de Linux; Linux es opcional y PyOS funciona sin él.

## 2. Estado por componente

| Componente | Estado | Pruebas |
|---|---|---|
| Selector de arranque (espera indefinida, flechas/número, PS/2 y serie) | **Implementado** | `tests/test_selector.py`, `uefi_smoke.py` (QEMU) |
| Detección de distribuciones (shim > grub > systemd-boot en `\EFI\<distro>\` de otras particiones FAT) | **Implementado** | unitarias con FS simulado; QEMU con disco Alpine |
| Chainload a Linux desde UEFI | **Implementado** | QEMU: GRUB → `Linux version 6.18` |
| Vuelta al selector si el cargador regresa o falla | **Implementado**; en UEFI real **sin probar** (requiere salir de GRUB) | `test_firmware_vuelve_al_selector…` (emulada) |
| `mode=term` / `mode=look` en la línea de comandos del kernel | **Implementado** | `test_modo_term_y_look_sin_instalar` |
| PyOS Term: `pyos`, `pkg`, `svc`, `dev`, `lx` | **Implementado** | `tests/test_term.py`, QEMU |
| Gestor de paquetes (`PYOSPKG 1`, dependencias, conflictos, `verify`, `remove`) | **Implementado**, repositorio **local** | idem |
| Servicios (`/etc/svc`, enable/disable persistente, pidfile verificado contra `/proc`) | **Implementado** | idem |
| Distribución de teclado en caliente (`dev kbd es|us`, syscall 49) | **Implementado** (solo PS/2) | QEMU |
| Subsistema Linux (`lx`, syscalls 50–56, `/proc/linux`) | **Implementado** con PyOS alojado sobre Linux | `test_lx_ejecuta_procesos_linux_reales` |
| Consola en modo crudo + pantalla ANSI (`ttyctl`, syscall 57; `hal/ansi.py`) | **Implementado** | `tests/test_games.py`, QEMU (capturas) |
| Juegos 2D (`arcade`) | **Implementado**, monocromo en UEFI | idem |
| PyOS LOOK: framebuffer, ratón PS/2, escritorio, ventanas, 7 aplicaciones ([`LOOK.md`](LOOK.md)) | **Implementado** | `tests/test_look.py` (emulada), `uefi_smoke.py` (QEMU+OVMF: arranque en LOOK, doble clic, terminal, salida a Term) |
| LOOK en VirtualBox | **Sin probar** por mí; requiere VBoxSVGA/VBoxVGA y ratón PS/2 | — |
| Camino nativo VMware SVGA II (SVGA activado) | **Escrito, sin probar** (QEMU lo deja en VBE) | — |
| Arranque Linux con Secure Boot | **No soportado** | ver §4 |

## 3. Ejecución dual

### 3.1 Modelo nativo: PVM
Los programas de PyOS son Python compilado a la ISA de la PVM, con aislamiento,
apropiación por instrucciones y syscalls como trampas. No cambia nada.

### 3.2 Modelo Linux
Solo existe cuando **PyOS corre alojado sobre un kernel Linux** (HAL emulada con
`--linux`). Un proceso PVM pide al kernel PyOS lanzar un programa; el kernel PyOS se
lo pide al kernel Linux, que crea un **proceso Linux real** (ELF real, sus syscalls,
su sistema de archivos). La separación es estricta:

| | Proceso PVM | Proceso Linux |
|---|---|---|
| Lo planifica | kernel PyOS | kernel Linux |
| Memoria | RAM de PyOS (paginada por el VMM PyOS) | memoria del kernel Linux |
| Ficheros | PyFS | sistema de archivos de la distro |
| Comunicación | — | **solo** stdin/stdout/stderr vía `lx_read/lx_write` |

El puente (`hal/emulated.LinuxBridge`) usa `subprocess` con tuberías no bloqueantes y
se sondea como una IRQ más (línea 11, `linux-bridge` en `/proc/interrupts`). `lx_read`
y `lx_wait` bloquean al proceso PVM en una cola de espera, igual que una tubería.
Los procesos Linux pertenecen al proceso PyOS que los creó (o sus descendientes);
si este muere, el kernel PyOS los mata.

**Por qué es opt-in (`--linux`):** cualquier proceso PVM con acceso al subsistema
puede ejecutar programas del host con los permisos del usuario que lanzó PyOS. Eso
anula el aislamiento de la PVM respecto al host, así que no se activa sin pedirlo.

### 3.3 Cómo usarlo
1. Instala una distribución (Ubuntu, Arch, Kali…) en un **segundo disco** de la VM,
   en modo UEFI. Su instalador crea `\EFI\<distro>\shimx64.efi` o `grubx64.efi`.
2. Arranca la VM con el disco de PyOS primero: el selector lista la distribución.
3. Elígela: arranca su kernel Linux real.
4. Dentro de Linux, copia el código de PyOS y ejecuta:
   ```bash
   python3 -m pyos mkimage ~/pyos.img
   python3 -m pyos run ~/pyos.img --linux
   ```
   y en PyOS: `lx uname -a`, `lx -i python3 -i`, `lx shell`, `lx ls / | grep etc`.

## 4. Limitaciones reales (no se fingen)

**No se pueden ejecutar los dos kernels a la vez con PyOS como anfitrión.**
Virtualizar Linux exige VT-x/AMD-V (`VMXON`, `VMLAUNCH`, VMCS), que son
instrucciones privilegiadas de máquina. Python sobre UEFI no puede emitir
instrucciones arbitrarias (no hay `ctypes` ni generación de código en `edk2-libc`,
y la regla del proyecto prohíbe escribir ensamblador). Emular un x86 completo en la
PVM sería posible en teoría pero ejecutaría Linux millones de veces más lento: no es
usable. La alternativa real es la inversa: **Linux como anfitrión y PyOS alojado**.

**En arranque nativo no hay aplicaciones Linux.** Sin kernel Linux no existe nadie que
cargue ELF, implemente `clone`/`mmap`/`futex`… Reimplementar la ABI de Linux en Python
sobre la PVM no permitiría ejecutar binarios x86 (la PVM no ejecuta código máquina).
`lx` lo explica y devuelve error.

**Firmware.**
- Secure Boot debe estar desactivado: el UEFI Shell no está firmado. Por la misma
  razón no se puede validar la cadena shim → GRUB desde PyOS; se lanza el cargador
  tal cual y el firmware decide.
- El selector solo ve particiones que el firmware monta (FAT: la ESP). Una distro
  instalada en BIOS/MBR sin ESP no aparece.
- Tras un chainload, el control es del cargador de la distro: si este arranca
  Linux, PyOS ya no existe en memoria (`ExitBootServices`). Si vuelve, PyOS reconecta
  los drivers del firmware, recupera teclado y UART y redibuja el menú.

**Memoria.** Los dos kernels nunca comparten memoria: no hay comunicación entre
el PyOS nativo y un Linux arrancado después, más allá de ficheros en una ESP común.

**Dispositivos.** En arranque nativo PyOS usa i8042, 16550, ACPI PM y PCI; no hay
red, USB ni disco propio (el disco es un fichero en la FAT del firmware). En modo
alojado los dispositivos son los de la HAL emulada; los reales los tiene Linux.

**Paquetes.** No hay red: el repositorio es local (`/var/pkg/repo`). Se pueden instalar
paquetes copiados al disco con `pkg install /ruta/paquete.pkg`.
