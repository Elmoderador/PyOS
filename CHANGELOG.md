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

## 2.0.0 — 2026-11-23 · Born from Update Center

Syscalls nuevas a partir de la 80 (ABI 2: `sysinfo()["abi"]` vale 2 y `sysinfo()["since"]` dice desde qué
ABI existe cada una); las 0–79 no cambian de significado (la 26, `statfs`, acepta ahora una ruta
opcional).

### ⚠ Cambios incompatibles
- **Un disco 1.x no arranca con la 2.0.** Disco nuevo + `python3 -m pyos migrate` (copia `/root`
  y `/etc`; el disco 1.x solo se lee). Ver `docs/INSTALAR_ACTUALIZAR_RECUPERAR.md`.
- **`/bin`, `/sbin`, `/lib` y `/usr` son de solo lectura** (volumen de sistema verificado):
  escribir ahí da `EROFS`. Lo del usuario va a `/usr/local` (`pkg` lo hace solo) y las rutas de
  `/bin`, `/sbin`, `/lib` y `/usr/share` lo encuentran ahí.
- **`LOOK_API` vale 2.** La API de apps dentro de LOOK no cambia (las de la 1.x funcionan igual)
  y la 2 añade ventanas de otros procesos. Lo que se rompe es la comprobación que recomendaba
  `docs/LOOK.md` en la 1.x (`if LOOK_API != 1: raise ...`): cámbiala por `if LOOK_API < 1`.
- **Capacidades por proceso:** la shell, LOOK y los programas del usuario ya no pueden usar
  `update.*`, `disk.raw` ni `sys.nice` (bajar la prioridad sigue permitido).
- LOOK y arcade son parte del sistema: se actualizan con UC y `pkg remove look` lo rechaza.

### Update Center y arranque A/B
- Arranque en dos conjuntos A/B (kernel + volumen de sistema) con manifiesto firmado
  (Ed25519); etapa 1 fija y `bootloader.zip` en dos copias en la ESP; registro de arranque,
  almacén de claves y estado de la etapa 1 por duplicado; 3 intentos para una versión nueva,
  *watchdog* del kernel y vuelta atrás automática con restauración de `/etc`.
- Volumen de sistema de solo lectura verificado por bloques (árbol de hashes tipo dm-verity).
- Almacén de claves con registros firmados: rotación y revocación sin reinstalar.
- `uc estado | buscar | descargar | instalar | importar | historial | volver`; `uc-lite`
  (siempre disponible, también sin `ucd`); `ucd` (estado, historial, política automática).
- **En línea (D3):** cliente de Releases de GitHub con TLS 1.3 en Python puro
  (`TLS_CHACHA20_POLY1305_SHA256`, X25519, certificados ECDSA P-256/P-384 y RSA), HTTP/1.1 con
  redirecciones, `chunked` y descargas reanudables; solo instala lo que esté firmado con una
  clave del sistema. Política `uc.auto` / `uc.tipos`; nunca reinicia por su cuenta.
- **Sin red:** paquete `.ucb` (`uc importar fichero` o `-` desde la entrada estándar).
- Herramienta del propietario `pyos/tools/release.py` (claves, assets de la Release, `.ucb`).
- Entrada «PyOS (versión anterior)» en el selector de arranque.

### Sistema
- Capacidades por proceso (`cap_get`/`cap_drop`, herencia, capacidades de fichero del sistema,
  canales reservados). `/proc/<pid>/status` muestra `Caps:`.
- Paquetes firmados `PYOSPKG 2` (syscall 110) en el repositorio del sistema.
- `svcd`: salud de los servicios esenciales; un servicio que arranca pero no responde no cuenta
  como sano (no se confirma una actualización con `ucd` colgado).
- `eventd`: permisos por tema y historial de avisos en `/var/lib/notify/history`.
- Criptografía en el kernel (syscall 112, por pasos para no parar el planificador):
  ChaCha20-Poly1305, X25519, ECDSA P-256/P-384, RSA PKCS#1 v1.5/PSS, SHA-2, HMAC.
- Con `kdiag=1` en la línea del kernel, `/proc/latency` informa también de la llamada más lenta
  de cada syscall (`slow_syscalls`) y de la rodaja y la medida de memoria más lentas.
- Corregido antes de publicar (regresión de la rama, no está en 1.x): un proceso que solo hacía
  syscalls rápidas no se expropiaba nunca (ver el informe de seguridad).

### Programas
- **Term 2.0** (`term`): hasta 9 sesiones (Alt+1..9, Alt+N, Alt+X); la shell avisa del estado
  de UC al entrar.
- `monitor` (CPU, memoria, procesos, almacenamiento, servicios), `diag` ampliado (integridad
  completa del sistema, arranque, claves; `-o fichero`), `notify`.
- **LOOK (Desktop 2.0):** 4 escritorios (Alt+1..4 o las marcas del botón PyOS), ventanas de
  otros procesos (`/lib/look2.py`), lanzador con búsqueda (Alt+L), Monitor, Diagnóstico,
  Actualizaciones, centro de avisos, Explorador (pestañas, búsqueda, vista previa), editor con
  resaltado de Python, interfaz de Paquetes, «Recordar ventanas» en Ajustes.
- **SDK:** `docs/SDK.md` (tabla de syscalls generada y comprobada), plantillas de programa y de
  ventana, `python3 -m pyos.tools.sdk nuevo | empaquetar | firmar`.

### Arranque UEFI
- **Python.efi con parches de PyOS** (`pyos/uefi/patches/`): `edk2.writemem` copiaba desde una
  dirección equivocada (longitud de 8 bytes escrita en un `int`), y PyOS lo aprovechaba copiando
  desde la página física 0. En un firmware que protege la página 0, LOOK se quedaba colgado con
  un fallo de página al arrancar. Ahora la copia rápida usa `writemem` corregido y nunca toca la
  página 0; sin el parche, el camino lento.
- LOOK muestra su versión real (2.0.0; ponía 1.0.0).
- Validación de arranque por hipervisor antes de entregar (`docs/VALIDACION_ARRANQUE.md`,
  `scripts/validate_boot_qemu.py`, `tests/qa/vbox_validate.ps1`).

### Idiomas
- **PyOS habla 9 idiomas (14 variantes):** castellano de España (el original) y de Latinoamérica,
  inglés de EE. UU. y del Reino Unido, portugués de Portugal y de Brasil, catalán (central,
  valenciano y de Andorra), euskera, gallego, alemán, francés e italiano. Se elige en
  Ajustes > Idioma o con la orden nueva `idioma <código>` (`idioma lista` los enseña).
- Todo lo que ve el usuario está traducido: LOOK, sus aplicaciones, la shell, las órdenes, los
  juegos, el Update Center y los mensajes de `init`. **El registro del kernel sigue en
  castellano** (es para diagnosticar) y los textos de error del sistema (`strerror`) siguen en
  inglés, como en Linux.
- Catálogos en `/usr/share/locale/<código>/<dominio>.cat`; la clave es el texto original
  (`tr()` / `trn()` en libpy, también para apps de terceros). Las variantes solo guardan lo que
  cambia respecto a su idioma base. Herramienta `python3 -m pyos.tools.i18n` (candidatos,
  extraer, comprobar, estado) que comprueba marcadores `%s` en orden, glifos y saltos de línea.
- Las traducciones no las ha revisado todavía ningún hablante nativo.

### Accesibilidad
- **Ajustes > Accesibilidad**, en cinco grupos con una explicación por opción:
  - *Ver mejor:* tamaño de todo al 100/150/200 % (texto con letra Terminus más grande, nítida,
    no escalada a bloques), puntero grande o muy grande, marca del teclado muy visible.
  - *Colores:* alto contraste (negro, blanco y amarillo), colores suaves (tema «Calma», sin
    blanco que deslumbre) y colores para daltonismo (paleta Okabe-Ito: nada depende de
    distinguir rojo y verde).
  - *Lectura:* lectura fácil (los mensajes importantes en frases cortas y palabras sencillas),
    espaciado amplio entre letras y líneas (dislexia) y guía de lectura en Notas, Ayuda e
    informes.
  - *Atención:* reducir movimiento, avisos tranquilos (no salen encima: se guardan y la barra
    dice cuántos hay), avisos que no se van solos y modo concentración (solo la ventana activa).
  - *Movilidad:* teclas fijas (Ctrl/Alt/Mayús de una en una), teclado lento (retardo, repetición
    y rebote), velocidad del doble clic y abrir con un solo clic.
- Todos los diálogos se manejan con el teclado: Tab / Mayús+Tab mueven el foco entre botones e
  Intro pulsa el que lo tiene. Los botones tienen el ancho de su texto en cualquier idioma.
- **Aviso de actualización nuevo:** ventana con «Instalar», «Más tarde» y «Qué trae», explicada
  en frases sencillas (qué trae, que no se pierde nada si falla) y que no se cierra sola.
- Syscall nueva **113 `kbdopts`** (teclas fijas y teclado lento en el driver PS/2) y
  `gfx_open(opts)` admite `zoom` y `cursor`. Distribuciones de teclado nuevas: `latam`, `gb`,
  `de`, `fr`, `it`, `pt`, `br`. Alt+número cambia de escritorio también con distribución
  española y Mayús+Tab llega a las aplicaciones.
- Fuentes grandes derivadas de Terminus Font (licencia SIL OFL 1.1 en
  `licenses/Terminus-Font-OFL-1.1.txt`; no se usa el nombre reservado).
- Límites, dichos claramente: no hay lector de pantalla (PyOS no tiene audio); el terminal de
  LOOK no se amplía; las teclas fijas no tienen indicador en pantalla; el 200 % necesita una
  pantalla de al menos 1600x1000; en QEMU la repetición de teclas la hace también el anfitrión,
  así que el teclado lento se nota menos que en hardware real.

### Otros
- LOOK pinta con doble búfer: cada fotograma se compone en memoria y se copia entero a la
  pantalla, con el cursor ya encima. Se acaba el parpadeo de ver las ventanas a medio pintar.
- Orden `turbo` (huevo de pascua, en los 9 idiomas; en `help`: «turbo: Baja 1ms»): «activa» el modo turbo, tarda
  ~1,6 s en ahorrarte 1 ms y reconoce que ese milisegundo no se puede medir.
- Kit de publicación (`scripts/release/`, `docs/PUBLICAR_2.0.0.md`): construye las imágenes con
  las claves del propietario en su equipo (Linux o Windows + WSL2), regenera `SHA256SUMS` y
  verifica sin claves privadas que las imágenes llevan sus claves y que la firma es válida.

### Seguridad
Informe: `docs/security/v2.0.0/README.md` (modelo de confianza de UC, fuzzers, fallos
encontrados durante el desarrollo y límites conocidos).

### Fallos que también tiene la 1.0.2 (reproducidos contra `v1.0.2`, corregidos aquí)
Ninguno se ha llevado a la rama 1.x: decidir si merecen una 1.0.3 es cosa del propietario.

- **Red: inundación de SYN.** Las conexiones semiabiertas no tenían tope (20 000 SYN → 20 000
  conexiones en el kernel). Ahora: 64 por puerto en escucha (cae la más vieja) y 1024 en total.
- **Red: tabla ARP y destinos sin resolver** sin tope; ahora 256 y 64.
- **DNS:** una consulta abandonada por una señal retenía un puerto 6 s, sin límite (un bucle
  agotaba los 16 384 puertos efímeros de todo el sistema); puerto de origen secuencial
  (RFC 5452 pide azar); caché sin tope; etiquetas de más de 63 bytes generaban paquetes mal
  formados.
- **ping:** las peticiones no tenían dueño. Otro proceso podía leer o pisar la respuesta, y
  entonces una señal al dueño acababa en un Oops que lo mataba.
- **Plazos heredados:** tras un `sleep` desde código llamado por el anfitrión, el siguiente
  `sleep_ms(1000)` dormía 3 s (o se acortaba).
- **Teclado PS/2:** el Mayús falso (`E0 2A`/`E0 AA`) soltaba el Mayús real; Pausa activaba
  Ctrl; el bloque numérico no escribía; Bloq Mayús no afectaba a ñ ni a ç.
- **Subsistema Linux (modo alojado):** `lx_spawn` no tenía tope de procesos del anfitrión;
  ahora 8 por proceso y 32 en total.
- **Reloj en UEFI:** el temporizador ACPI PM (24 bits) da la vuelta cada 4,69 s; si una
  syscall larga no lo leía en ese tiempo, el reloj del kernel se atrasaba 4,69 s por vuelta
  (medido: 25 s reales contados como 4). Ahora se recuperan contra el RTC del firmware.
- **Límite de CPU esquivable:** tras una syscall larga solo se cobraban 50 ticks (0,5 s); una
  compilación de 3,2 s contaba 0 s de CPU. Ahora se cobran todos, y `uptime_ms` sale del reloj
  (LOOK decía "escritorio listo en 2,1 s" en UEFI; en realidad eran 5,1 s).
- **Compilar congelaba el sistema** (no se podía expropiar): en QEMU, 64 KiB ~6 s y 256 KiB
  ~23 s; `exec` aceptaba ficheros de hasta ~4 MiB. Ahora se compila por pasos (abajo), con
  un tope de 256 KiB por fichero.

### Compilación por pasos
- El análisis sintáctico se hace por trozos de sentencias completas (también dentro de
  `class`/`def`) y el árbol es idéntico al de `ast.parse` entero, posiciones incluidas; los
  ámbitos y la generación de código ceden el control tras cada sentencia. Bytecode idéntico
  byte a byte al compilador anterior (copia congelada en `tests/ref/compiler_ref.py`).
- `exec`, `spawn`, `include` y `pycompile` avanzan unos milisegundos por turno y ceden la CPU
  (`Yield`). Una señal la cancela (`EINTR`); la muerte del proceso la libera; lo que se compila
  a la vez está acotado (512 KiB de fuente; quien no cabe espera).
- Nuevo `/proc/latency`: hueco más largo entre sondeos de interrupciones (total y por segundo)
  y paso de compilación más largo.
- Medido en QEMU (UEFI): hueco máximo compilando LOOK ~0,1 s (antes ~4,5 s); 180 KiB ~0,3 s
  (antes ~10 s). Coste: LOOK carga un 10–30 % más despacio.

### Recolector de basura
- La colección completa (generación 2) ya no cae en mitad del trabajo de un proceso: se hace en
  reposo, y con carga continua se fuerza espaciada (≤ ~5 % del tiempo). En QEMU, el paso de
  compilación más largo bajó de 250–300 ms a ~70 ms. `/proc/latency` informa de las colecciones.

### Rendimiento
- Compilar LOOK en el arranque UEFI: de ~5,8 s a ~4,3 s (−27 %), con salida idéntica byte a byte.

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
