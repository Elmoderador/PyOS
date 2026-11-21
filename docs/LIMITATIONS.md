# Limitaciones y decisiones de diseño

## 1. Lo que sigue sin ser Python

| Pieza | Por qué | Escrito por nosotros |
|---|---|---|
| `Python.efi` (CPython 3.6.8 para UEFI) | Python necesita un intérprete; no hay otra forma de ejecutar Python en una CPU | No: TianoCore/Intel, compilado sin modificar |
| UEFI Shell (`BOOTX64.EFI`) | Lanzador del intérprete | No: TianoCore, sin modificar |
| Firmware UEFI de la VM | Viene con la máquina, como la BIOS de un PC | No |

Ningún fichero de este repositorio contiene C, C++, Rust ni ensamblador.

## 2. Interrupciones por sondeo
Para recibir una IRQ asíncrona de la CPU hace falta un manejador de interrupción en
código máquina, y eso no se puede escribir sin ensamblador. PyOS hace lo que haría un
kernel en modo *polling*: entre rodajas de 300 instrucciones de la PVM lee los
registros de estado del temporizador ACPI, el i8042, la UART y `PM1_STS`, y despacha
por la IDT los vectores de las líneas activas. La latencia es de una rodaja.

## 3. El firmware sigue activo
PyOS no llama a `ExitBootServices`, porque no puede hacerse desde Python. Mientras
PyOS corre, el firmware mantiene su temporizador interno. PyOS le **quita** el
teclado y el puerto serie (`disconnect`) para manejarlos él, y sigue usando del
firmware la pantalla (texto) y el acceso FAT al fichero `disk.img`.

## 4. La PVM frente a CPython
- Las expresiones generadoras se evalúan de forma ansiosa, como una lista.
- Las comprensiones no tienen ámbito propio: su variable se ve fuera.
- No existen `import`, `async/await`, `super()` sin argumentos, metaclases ni `:=`.
- Cuando el código del host llama a código de usuario (por ejemplo `sorted(key=...)`
  o `__eq__`), se ejecuta de forma anidada y no puede ser expulsado de la CPU. Las
  syscalls que bloquearían devuelven `EAGAIN` en ese contexto.
- En `fork()`, los objetos *clase* se comparten entre padre e hijo; las instancias
  y todo lo demás se copia.
- Rendimiento: la PVM es un intérprete escrito en Python que corre sobre otro
  intérprete. Va del orden de 50-100 veces más lenta que CPython nativo. En
  QEMU sin aceleración, `spin` hace unas 3.000 iteraciones por segundo.

## 5. Memoria
Las tablas de páginas y los marcos están en RAM física real, y los segmentos de
código se cargan en memoria virtual. Aun así, los objetos Python de cada programa
(listas, cadenas…) viven en el heap del intérprete. La memoria paginada cubre los
segmentos cargados, el heap (`sbrk`), `mmap` y todo acceso con `peek`/`poke`.

## 6. Otras
- Una sola CPU y sin usuarios ni permisos.
- Red: solo e1000, IPv4, sin TLS; detalles en [`NET.md`](NET.md).
- PyFS no tiene journaling (lo compensa con fsck) y el tamaño máximo de fichero es de unos 4 MiB.
- La distribución de teclado inicial va en la línea de comandos (`kbd=es`/`kbd=us`) y se
  cambia en caliente con `dev kbd`.
- PyOS LOOK y sus límites (velocidad, adaptadores soportados, uso del fallo de
  `edk2.writemem` como copia rápida): ver [`LOOK.md`](LOOK.md).
- Doble kernel, Linux y sus límites (sin virtualización, sin apps Linux en arranque
  nativo, Secure Boot): ver [`ARCHITECTURE.md`](ARCHITECTURE.md).
- **Secure Boot debe estar desactivado:** el UEFI Shell no está firmado por Microsoft.
- En VirtualBox con Hyper-V activo (modo "NEM"), cada acceso a un puerto de E/S
  cuesta más, pero funciona.

## 7. Siguientes pasos posibles
- PyOS Term sobre el framebuffer (consola gráfica propia con colores), sin la consola
  de texto del firmware.
- Protocolo para que otros procesos abran ventanas en LOOK.
- Driver ATA/AHCI en Python para leer el disco sin pasar por el firmware.
- Driver virtio-net (más rápido que e1000 en QEMU/KVM) y TLS en Python puro.
