# PyOS LOOK

Entorno gráfico de PyOS: escritorio, barra de tareas, menú, ventanas que se mueven,
redimensionan, maximizan y minimizan, y aplicaciones. Todo en Python: el kernel maneja
la pantalla y el ratón; LOOK es un proceso normal de la PVM que usa sus syscalls.

## Cómo se arranca
* En el selector de arranque: **1. PyOS LOOK** (`mode=look`). Si LOOK no está instalado
  o la pantalla no se puede usar, init lo dice y arranca PyOS Term.
* Desde PyOS Term: `look`. Al salir (menú PyOS → *Salir a PyOS Term*) vuelves a la shell.
* Es un paquete: `pkg remove look` / `pkg install look`. Viene instalado.

## Qué incluye

| Aplicación | Qué hace |
|---|---|
| **Terminal** | Shell real de PyOS en una ventana (tuberías al proceso `sh`): edición de línea, historial desplazable (RePág/AvPág), secuencias ANSI. Los programas a pantalla completa (`arcade`, `snake`...) funcionan dentro: el kernel les da un tamaño de terminal virtual y el teclado vuelve a LOOK al salir. |
| **Archivos** | Navegar, abrir, nueva carpeta, renombrar, borrar, "Terminal aquí". Los `.py` de `/bin` se ejecutan en una Terminal; el resto se abre en Notas. |
| **Notas** | Editor de texto: abrir, guardar (Ctrl+S), guardar como, flechas, Inicio/Fin, autoindentado. |
| **Procesos** | Lista de `/proc` cada 2 s; Terminar (SIGTERM) y Matar (SIGKILL). |
| **Aplicaciones** | Interfaz de `pkg`: instalar y desinstalar paquetes del repositorio local. |
| **Ajustes** | Tema (Azul, Bosque, Grafito), teclado es/us, servicios (`svc`), información del sistema, corrección horaria. Se guardan en `/etc/look.conf`. |
| **Navegador** | HTTP/1.0 sobre la pila TCP/IP de PyOS, en un proceso aparte (`/lib/look/fetch.py`): el escritorio no se congela mientras carga; Esc o X cancelan. También `file:///ruta`. HTML básico (títulos, párrafos, listas, negrita, enlaces, `<pre>`, entidades), Ctrl+L, historial (Retroceso), RePág/AvPág y rueda. Sin TLS, JS, CSS ni imágenes. Ver [`NET.md`](NET.md). |
| **Paint** | Lienzo de 640x400: lápiz, goma, línea, rectángulo, caja, cubo de pintura; 4 grosores, 16 colores, deshacer (Ctrl+Z), abrir y guardar BMP (Ctrl+O / Ctrl+S). |
| **Imágenes** | BMP (1/4/8/24/32 bits sin comprimir), PPM y PGM binarios. Ajustar, zoom, arrastrar para desplazar, ← → recorren la carpeta, "Editar" la abre en Paint. Ejemplos en `/usr/share/images`. |
| **Calculadora** | + − × ÷ % ^ y paréntesis con precedencia correcta (analizador propio, sin `eval`); teclado o ratón. |
| **Juegos** | El menú `arcade` en una ventana. |
| **Acerca de** | Versión, adaptador de vídeo y resolución. |

Ratón: clic, doble clic (iconos, abrir, maximizar con doble clic en el título),
arrastrar títulos, esquina inferior derecha para redimensionar, clic derecho en el
escritorio para el menú contextual.
Teclado: **F1** o tecla **Windows** abren el menú PyOS; **Alt+Tab** cambia de ventana;
**Alt+W** o **F4** cierra la ventana activa; **Alt+T** abre una terminal; sin ventanas,
flechas + Intro recorren los iconos. Se puede usar LOOK entero sin ratón.

## Cómo funciona

```
 proceso LOOK (PVM)                      kernel PyOS                       hardware
 ───────────────────                     ───────────                       ────────
 WM: ventanas, daños ─ gfx_draw(lista) ─► Painter (recorte, texto, rects,  ─► framebuffer lineal
 apps (Terminal...)                       degradados, mapas de bits)           del adaptador (BAR PCI)
 bucle de eventos ◄── gfx_poll(timeout) ─ eventos de ratón (IRQ 12)       ◄── i8042 puerto AUX
                                          + teclas (consola en modo crudo) ◄── i8042 teclado
                                          cursor del ratón (lo mueve el kernel)
```

* **Syscalls** 58–62: `gfx_open`, `gfx_draw`, `gfx_poll`, `gfx_close`, `gfx_cursor`.
  Un solo dueño de la pantalla; si muere, el kernel devuelve la consola de texto.
  Las órdenes se validan (tipos, rangos, tamaño de la lista): un proceso no puede pasar
  al kernel nada que no sean enteros, colores, cadenas y listas acotadas.
* **Redibujado por daños**: LOOK acumula los rectángulos que cambian, los fusiona y
  para cada uno pinta escritorio → ventanas (de abajo arriba) → barra → menú, con el
  recorte del kernel. Solo se redibuja lo que cambia.
* **Cursor**: el kernel lo dibuja guardando los píxeles de debajo (lectura rápida del
  framebuffer) y lo mueve en la interrupción del ratón, sin esperar a LOOK.
* **Doble clic**: se mide con la marca de tiempo del kernel de cada paquete del ratón,
  no con la hora a la que LOOK procesa el evento.
* **Fuente**: la 8×19 de la consola gráfica de edk2 (`LaffStd.c`, BSD), extraída como
  datos por `pyos/tools/mkfont.py`: ASCII, Latin-1 completo, cajas y flechas.

### Pantalla real sin GOP
Python sobre UEFI no puede llamar a protocolos del firmware (no hay `ctypes`), así que
no se usa GOP. Se usa el modo que el firmware ya dejó puesto y se escribe en la memoria
de vídeo:

* **Bochs/QEMU std-VGA, VirtualBox VBoxVGA/VBoxSVGA**: registros VBE DISPI (puertos
  0x1CE/0x1CF) para leer resolución, bpp y ancho virtual; dirección del framebuffer en
  el BAR de memoria del dispositivo PCI de vídeo.
* **VMware SVGA II** (QEMU `-vga vmware`, VMSVGA): registros SVGA por su BAR de E/S.
  En QEMU el firmware lo deja en modo VBE y se usa ese camino (probado); el camino SVGA
  nativo está escrito pero **sin probar**.
* Solo modos de 32 bpp.

### Copia rápida: el fallo de `edk2.writemem`
`writemem_dword` escribe 4 bytes por llamada: una pantalla de 1024×768 serían ~786.000
llamadas. `edk2.writemem` está roto en edk2-libc: con `PY_SSIZE_T_CLEAN` el formato
`s#` escribe una longitud de 64 bits sobre un `int`, y la mitad alta (cero) pisa la
mitad baja del puntero al búfer. Como los objetos de Python están por debajo de 4 GiB,
el resultado es una copia **desde la dirección física 0** hacia el destino, con la
longitud correcta. Es determinista (mismo binario siempre), así que LOOK lo usa:

1. Se guarda la página física 0 (en UEFI es la página "nula": la reserva el núcleo DXE
   como `BS_Code` para detectar punteros nulos; nadie la usa).
2. Para un color, se escribe un píxel en la dirección 0 y se duplica con `writemem`
   desde 0 hacia 4·L (1 + log₂ n llamadas).
3. Cada tramo horizontal de ese color es **una** llamada a `writemem`, de hasta 1024
   píxeles. Un rectángulo de alto *h* cuesta *h* llamadas; un glifo, 1 por tramo.
4. Al cerrar LOOK la página 0 se restaura.

Antes de usarlo, una autoprueba en RAM propia comprueba que `writemem` copia de verdad
desde la página 0 y respeta la longitud. Si no (otro binario, otro firmware), se usa el
camino lento píxel a píxel, que siempre funciona. `/proc/gfx` dice cuál está activo.
No se ha escrito ni parcheado código C para esto.

## Requisitos y configuración de la VM

* Adaptador de vídeo con VBE: QEMU `-vga std` (por defecto) o `-vga vmware`;
  VirtualBox **VBoxSVGA** o **VBoxVGA**. Con VMSVGA (lo que VirtualBox pone por defecto
  para "Linux 64") puede no funcionar: cámbialo.
* Ratón **PS/2** (no "tableta USB"): PyOS no tiene driver USB. Sin ratón LOOK sigue
  siendo usable con el teclado.
* `gfxtest` (en PyOS Term) muestra una carta de ajuste y el adaptador detectado.

VirtualBox, con la VM apagada:
```powershell
& $vb modifyvm PyOS-v3 --graphicscontroller vboxsvga --vram 32 --mouse ps2 --keyboard ps2
```
Con ratón PS/2, VirtualBox "captura" el puntero al hacer clic dentro de la VM; se
suelta con la tecla anfitrión (Ctrl derecho).

## Limitaciones
* Velocidad: el kernel dibuja en Python y LOOK corre en la PVM (un intérprete dentro de
  otro). En QEMU sin aceleración abrir una ventana tarda segundos; con virtualización
  por hardware es mucho más rápido, pero no es un escritorio de 60 fps. Mover ventanas
  redibuja la zona afectada en cada evento del ratón.
* Las aplicaciones de LOOK son parte del proceso LOOK; los programas externos se usan
  en ventanas de Terminal (no hay protocolo para que otros procesos creen ventanas).
* Varias Terminales comparten la consola en modo crudo: Ctrl+C va al último programa en
  primer plano que fijó cualquiera de ellas.
* Sin aceleración gráfica, sin transparencias ni suavizado, una sola pantalla, fuente
  fija 8×19, sin portapapeles.
* La hora es la del reloj del firmware (RTC); se corrige en Ajustes → Reloj.
* En VirtualBox **no lo he podido probar** (solo QEMU+OVMF y la máquina emulada).


## Ratón, ventanas e imágenes

* **Rueda del ratón.** El kernel prueba la secuencia IntelliMouse (frecuencias 200/100/80 e ID 3)
  y, si el ratón la acepta, lee paquetes de 4 bytes. `/proc/gfx` muestra "PS/2 con rueda". La rueda
  desplaza Terminal (historial), Archivos, Notas, Procesos, Aplicaciones, Navegador, Paint y el
  visor, y mueve la selección de los menús.
* **Encajar ventanas.** Arrastrar una ventana al borde izquierdo o derecho la deja en media pantalla;
  al borde superior, maximizada. Se ve un marco de previsualización. Al volver a arrastrarla recupera
  su tamaño.
* **Imágenes en el kernel.** Nueva orden gráfica `("image", x, y, w, h, rgb, escala)`: se convierte
  solo lo que cae en el recorte, y los tramos de un mismo color van como un solo `span` (una sola
  llamada a `writemem` en UEFI). Lo que no se repite va píxel a píxel (`writemem_dword`), así que en
  UEFI una foto se dibuja mucho más despacio que un dibujo de colores planos.
* **Navegador asíncrono:** la descarga va en un proceso propio conectado por una tubería no bloqueante.

### Límites
* El cubo de pintura usa búsquedas galopantes con comparaciones de bytes nativas; aun así, en áreas muy
  fragmentadas es lento en la PVM.
* Paint y el visor guardan la imagen entera en memoria del proceso: máximo 1 Mpx para editar, 4 Mpx para ver.
* No hay compresión: ni PNG ni JPEG (harían falta zlib/Huffman en Python puro dentro de la PVM).

### Portapapeles, archivos, juegos y fallos aislados

* **Portapapeles.** Notas: selección con el ratón (doble clic = palabra), Ctrl+A/C/X/V, buscar
  (Ctrl+F, F3). Terminal: seleccionar con el ratón copia y el clic derecho pega (como en X11);
  Ctrl+C copia si hay selección y, si no, interrumpe el programa en marcha *de esa terminal*.
  Campos de texto y barra del Navegador: Ctrl+V/Ctrl+C.
  Para eso la consola tiene un modo crudo sin señales (`ttyctl("raw", "nosig")`, como `cfmakeraw`)
  y `ttyctl("fg")` devuelve los procesos en primer plano; cada terminal de LOOK solo interrumpe
  los hijos de su shell (`PPid` en `/proc/<pid>/status`).
* **Archivos.** Menú contextual (clic derecho): abrir, abrir con Notas/Navegador/Imágenes/Paint,
  copiar, cortar, pegar, renombrar, borrar, propiedades. Ctrl+C/X/V con archivos y carpetas (copia
  recursiva; "nombre (2)" si ya existe), borrado recursivo con confirmación que dice cuánto se borra,
  Ctrl+L o clic en la ruta para ir a una carpeta, Supr, F2, F5.
* **Juegos.** "Juegos" abre un centro con **Buscaminas** (3 niveles, primer clic seguro, bandera con
  clic derecho, doble clic en un número despeja alrededor, mejores tiempos en `/var/games`) y
  **Serpiente** gráfica; el Arcade de terminal sigue ahí. Solo se repintan las casillas que cambian.
* **Clic derecho en ventanas.** El WM entrega `"right"` a la aplicación que hay debajo.
* **Fallos aislados.** Si una aplicación lanza una excepción, LOOK no se cae: muestra el error
  (`repr` de la excepción), lo apunta en `/var/log/look.log` y, si falló al dibujarse o en segundo
  plano, cierra solo esa ventana.

### Escritorio
* **Fondo de escritorio** con imagen (Ajustes → Apariencia): BMP/PPM escalado por un entero hasta
  cubrir la pantalla. Con dibujos de colores planos es rápido también en UEFI; una foto se pinta
  píxel a píxel y cuesta más al mover ventanas.
* **Calendario** al pulsar el reloj; **menú de cada tarea** con clic derecho en la barra
  (minimizar, maximizar, cerrar); en los menús una **letra salta** a la opción que empieza por ella.
* **Avisos** (notificaciones) abajo a la derecha: Paint al guardar, Archivos al pegar, el Navegador
  cuando termina una página que está en segundo plano. Las apps pueden usar `self.wm.toast(texto)`.
* **Ayuda** (menú PyOS → Ayuda): todos los atajos de teclado y ratón.

## Rendimiento y robustez

**Rendimiento en hardware real.** El coste de dibujar en UEFI es el número de llamadas a
`edk2.writemem` (una por tramo de color). Medido con un banco de pruebas en la máquina emulada:

| Operación | Antes | Ahora |
|---|---:|---:|
| arrastrar una ventana (10 pasos) | 166 000 | 93 000 (contorno) / 125 000 (contenido) |
| abrir y cerrar el menú (con el ratón) | 44 000 | 26 000 |
| mover el ratón (por paquete) | ~450 | ~250 |
| teclear en la Terminal (por letra) | cientos | ~30 |
| teclear en Notas (por letra) | cientos | ~24 |

Cómo: oclusión (si una ventana o el menú tapan toda una región, no se pinta lo de debajo), daño
de ventanas como cuerpo + tiras de sombra, mover = daño de la posición nueva + lo que queda al
descubierto de la vieja, fusión de regiones solo si se solapan de verdad, degradados agrupados
por color en el kernel, cursor que solo toca los píxeles de la flecha y que no se borra en
fotogramas que no lo cruzan, repintado por filas en Terminal y Notas, y **contorno al mover**
(Ajustes → Apariencia; "Automático" = contorno en pantallas reales, contenido en la emulada).
LOOK anota en el log del kernel cuánto tarda en estar listo (`dmesg`): en QEMU sin aceleración,
2,3 s a 1280x800.

**Robustez.** `tests/look_fuzz.py` abre cada aplicación y le manda clics, dobles clics, clics
derechos, arrastres, rueda y teclas aleatorias; cualquier excepción queda en `/var/log/look.log`.
Encontró un fallo real (lista vacía + flecha abajo -> índice -1 en Archivos), ya corregido en todas
las listas. El registro de errores incluye ahora la traza de la PVM (fichero:línea y función),
gracias a la syscall `exctb`. Las terminales cerradas ya no dejan procesos zombi.

**Detalles.** Botones que se resaltan al pasar el ratón; diálogos manejables con Tab/flechas/Intro
y foco visible; en avisos que pueden perder trabajo el botón preseleccionado es "Cancelar";
Notas pregunta antes de cerrar con cambios, y salir de LOOK o apagar avisa de lo que no está
guardado; tema de **alto contraste**; mínimos de tamaño por aplicación; "+N" en la barra de
tareas cuando no caben todas las ventanas; ventanas centradas en pantallas pequeñas; etiquetas
del escritorio sin cortar; Ayuda que parte las líneas largas; Navegador con listas compactas
y una sola línea en blanco entre párrafos; LOOK no sondea cada 40 ms por tener una terminal abierta.

## Crear aplicaciones para LOOK

Cualquier `.py` en `/usr/share/look/apps/` se carga al arrancar LOOK, en el mismo espacio de nombres
que LOOK: tiene `Window`, `T` (colores del tema), `FW`/`FH` (tamaño de letra), `d_button`, `d_field`,
`clip_text`, `clip_get`/`clip_set` y toda la libpy. Para salir en el menú PyOS basta con añadirse a
`LOOK_APPS`. Ejemplo completo: `/usr/share/look/apps/reloj.py` (reloj y cronómetro).

```python
class Hola(Window):
    def __init__(self):
        Window.__init__(self, "Hola", 300, 160)
        self.n = 0
        self.add_button(20, 80, 120, 30, "Púlsame", self.inc, True)

    def inc(self):
        self.n += 1
        self.redraw()

    def draw_content(self, g, x, y, w, h):
        g.append(("text", x + 20, y + 30, "Pulsado %d veces" % self.n, T["text"], None))

LOOK_APPS.append(("Hola", "app", Hola))
```

Coordenadas: `draw_content` recibe la esquina absoluta del contenido; `on_mouse(tipo, x, y, b)` recibe
coordenadas relativas al contenido y `tipo` es `down`, `up`, `drag`, `double`, `right` o `wheel` (con
`b` = pasos de rueda). Órdenes de dibujo: `rect`, `frame`, `text`, `vgrad`, `bitmap`, `image`.
Un plugin con errores de sintaxis no impide arrancar: LOOK avisa al inicio y sigue.

**Compatibilidad.** `LOOK_API` (hoy `1`) es la versión de esta interfaz. Solo sube cuando un
cambio rompe plugins existentes, y el CHANGELOG lo anuncia. Un plugin puede protegerse así:

```python
if LOOK_API != 1:
    raise RuntimeError("este plugin necesita LOOK_API 1")
```
