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

## 2.0.0 — próximamente · Update (▮▮▮▮ ▮▮▮▮ ▮▮▮▮▮▮ ▮▮▮▮▮▮)

| Idioma | |
|---|---|
| Castellano (España) | V2.0.0 próximamente |
| Castellano (Latinoamérica) | V2.0.0 muy pronto |
| English (US) | V2.0.0 coming soon |
| English (UK) | V2.0.0 arriving shortly |
| Português (Portugal) | V2.0.0 brevemente |
| Português (Brasil) | V2.0.0 em breve |
| Català | V2.0.0 properament |
| Català (Andorra) | V2.0.0 properament |
| Valencià | V2.0.0 pròximament |
| Euskara | V2.0.0 laster |
| Galego | V2.0.0 proximamente |
| Deutsch | V2.0.0 demnächst |
| Français | V2.0.0 bientôt disponible |
| Italiano | V2.0.0 prossimamente |
| Andalú | V2.0.0 prósimamente, quillo |

> - ▮▮▮▮▮▮ se ▮▮▮▮▮▮▮▮ solo. Y si sale mal, ▮▮▮▮▮▮ solo.
> - Habla 15 idiomas. Bueno, 14. El 15.º es andalú y solo sale aquí.
> - 551 tests. Ninguno en verde a la primera.
> - Escribe `turbo`. No servirá de nada, pero escríbelo.

---

## 1.0.2 — 2026-11-22 · Security (Shield Update II)

Cierra los tres límites que la 1.0.1 dejó documentados. `LOOK_API` sigue en 1 y ninguna
syscall cambia de significado. Para poder imponer los límites hay **interfaces nuevas**
(syscalls 77–79, un argumento opcional de `uptime`, `ulimit` en la shell) y **programas que
antes funcionaban pueden fallar ahora con un error claro** (ver "Límites nuevos").

### CPU: ninguna instrucción puede congelar el planificador
El planificador solo expulsa a un proceso entre instrucciones de la PVM, y una instrucción podía
ejecutar C del anfitrión sin fin. En 3.6 (el intérprete del arranque UEFI), 9 de 10 ataques
congelaban el sistema en la 1.0.1; en la 1.0.2 ninguno lo deja sin control más de ~0,2 s.
- Enteros de como mucho 131 072 bits (`10 ** 10 ** 8`, `1 << (1 << 40)`, `int.from_bytes`),
  `pow()` con módulo con un modelo de coste, `round(x, -10 ** 8)` sin calcular la potencia.
- Las builtins de C (`sum`, `max`, `sorted`, `list`, `str.join`, `[*x]`...) recorren como mucho
  1 000 000 de elementos por llamada, o 200 000 si vienen de un iterador perezoso.
- **Código de usuario llamado desde C** (`sorted(key=...)`, `__hash__`, un generador que
  consume `sum()`) se ejecutaba sin expropiación: ahora comparte un presupuesto de 250 000
  instrucciones por rodaja y, si lo agota, falla con `TimeoutError`.
- Anchos y precisiones de formato de como mucho 1 048 576 (`'{:>1000000000}'`, `'%*d'`, f-strings).

### Memoria: cuota por proceso
- Cada proceso tiene una cuota (64 MB por defecto; `memquota=` en la línea del kernel). Las
  reservas grandes (`bytes(n)`, `'x' * n`, `ljust`, `replace`, `join`...) se comprueban **antes**
  de reservar (`MemoryError` en el programa); lo que se acumula poco a poco lo mide un recorrido
  del heap por partes entre rodajas, y el proceso que se pasa recibe SIGKILL.
- El CPython del arranque UEFI está compilado sin pymalloc, así que la señal de "este proceso
  crece" sale de los contadores del recolector de basura. Sin ella, en la prueba UEFI un
  proceso llegó a dejar sin memoria la VM de 512 MB antes de que se le midiera (encontrado y
  corregido antes de publicar; `tests/test_quota.py` simula ahora ese CPython).
- `setrlimit`/`getrlimit` (77, 78) y `ulimit [-m MB] [-t S]` en la shell: límites de memoria y de
  tiempo de CPU que heredan los hijos y que solo se pueden bajar.
- `/proc/<pid>/status`: `VmHeap`, `VmHeapPeak`, `MemQuota`, `CpuLimit`.

### httpd concurrente
- Nueva syscall `poll()` (79): espera en varios descriptores a la vez (sockets, tuberías).
- `httpd` es un bucle de eventos: atiende hasta 32 conexiones a la vez; con todas ocupadas,
  expulsa a la más antigua que aún no ha terminado de enviar su petición. Con 40 conexiones
  Slowloris abiertas, una petición legítima tarda lo mismo que sin ellas (dentro del ruido de
  medida); en la 1.0.1 cada una le añadía 10 s.
- `uptime(True)` / `uptime_us()`: microsegundos del reloj monótono, para medir latencias.

### Fuzzer de red con estado
- `tests/netfuzz.py` graba una sesión como guion y lleva la pila al estado exacto en que espera
  cada trama (arranque DHCP, consulta DNS abierta, conexión enviando), muta esa trama con
  mutaciones que entienden el protocolo y comprueba cuelgues e invariantes (direcciones de 4
  bytes, MSS válido), no solo excepciones. Contra el código de la 1.0.0 encuentra 10 fallos
  distintos —las cinco clases de fallo de red de la 1.0.1— donde el fuzzer anterior encontraba 0.
- **Corregido en el fuzzer de la 1.0.1:** `fix_checksums` sumaba el relleno Ethernet y rompía la
  suma de toda trama TCP de menos de 60 bytes (SYN, SYN-ACK, ACK): sus mutaciones nunca pasaban
  de la comprobación de la suma.
- `tests/sysfuzz.py` cubre también las syscalls nuevas: encontró que `uptime` evaluaba
  `if precise:` sobre un objeto del usuario (código del usuario dentro del kernel). Corregido
  antes de publicar.

### Límites nuevos (pueden romper programas)
- `sum(range(2_000_000))` y similares fallan con `OverflowError`: hay que recorrer con un bucle.
- Enteros de más de 131 072 bits, anchos de formato de más de 1 048 576, `sorted(key=...)` con
  más de ~10 000 elementos (presupuesto anidado): errores en lugar de congelar el sistema.
- Coste: la PVM es un ~8 % más lenta en el banco de pruebas (`tests/pvm_bench.py`, CPython 3.6).

### Herramientas
- `tests/secbench.py`: ataques de CPU, memoria, latencia de `httpd` y comparación de fuzzers.
- `tests/test_quota.py`, `tests/test_poll.py`, `tests/uefi_quota.py` (cuotas en el arranque UEFI real).

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
