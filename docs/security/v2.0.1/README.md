# Informe de seguridad — PyOS 2.0.1

Versión solo de seguridad. Todas las cifras se han medido en local; las claves usadas en las
pruebas son desechables y no se ha generado ni usado ninguna clave real de publicación.

## 1. Cómo se ha buscado

Repaso de todo lo que lee datos que vienen de fuera en la 2.0.0, buscando «hasta la última mota
de polvo»:

- Cliente HTTPS (`/lib/https.py`): URL, cabeceras, estado, `chunked`, redirecciones, reanudación.
- TLS 1.3 y X.509 (`/lib/tls.py`, `/lib/x509.py`): orden de los mensajes, tamaños, extensiones.
- Formatos del Update Center: JSON de GitHub, manifiestos, firmas, registros de claves, `.ucb`.
- Paquetes (`pkg`), DNS del kernel, syscalls `update_*` y capacidades.
- El modelo de confianza: el «ataque de congelación», que la 2.0.0 dejaba como límite conocido.

Cada fallo se reprodujo primero contra el código de la 2.0.0 (zip publicado, `99c5acb1…`) y luego
se comprobó que la 2.0.1 lo bloquea.

## 2. Banco de ataques: 2.0.0 contra 2.0.1

`python3 tests/secbench201.py <árbol>` ejecuta los mismos ataques con el código de cada árbol.
«Funciona» = el atacante consigue lo que busca (o el programa cae con una excepción no
controlada); «bloqueado» = se detecta o se corta sin efecto.

| Ataque | 2.0.0 | 2.0.1 | Qué pasaba en la 2.0.0 |
|---|---|---|---|
| UC: el servidor esconde la versión nueva (congelación) | funciona | **bloqueado** | No había sello de tiempo: la lista sin la versión nueva se creía |
| UC: `Retry-After` de años | funciona | **bloqueado** | Update Center bloqueado 1 157 407 días (ahora, 24 h como mucho) |
| HTTPS: trozo `chunked` de 2 GiB | funciona | **bloqueado** | El cliente acumulaba en memoria lo que llegaba (2 560 KiB al cortar la prueba) |
| HTTPS: inyección de cabeceras por la URL | funciona | **bloqueado** | La petición salía con la cabecera inyectada |
| HTTPS: redirección relativa a otro host | funciona | **bloqueado** | La segunda petición iba a `api.testevil.test` |
| HTTPS: al reanudar, `206` de otro trozo | funciona | **bloqueado** | El fichero quedaba `abcXYZdef` |
| HTTPS: al reanudar, `200` completo | funciona | **bloqueado** | Se añadía al final (9 bytes de 6) antes de empezar de nuevo |
| HTTPS: estado con cifras no ASCII (`'³00'`) | funciona | **bloqueado** | `ValueError` sin controlar: el cliente caía |
| X.509: CA con `nameConstraints` críticas | funciona | **bloqueado** | Se aceptaba como CA sin límites |
| TLS: mensaje post-handshake de 16 MiB | funciona | **bloqueado** | Esperaba a juntar 16 MiB en memoria |
| JSON: UTF-8 no válido | funciona | **bloqueado** | `UnicodeDecodeError` sin controlar |
| DNS: respuesta de otra IP y con otra pregunta | funciona | **bloqueado** | Se aceptaba |
| UCB: 2 000 registros de claves | funciona | **bloqueado** | Leía los 2 000 antes de fallar por otra cosa |
| pkg: tamaño `+1` en la cabecera | funciona | **bloqueado** | Se aceptaba |

**14 de 14 funcionan en la 2.0.0 y 14 de 14 se bloquean en la 2.0.1.**
Resultados completos: [`data/ataques-2.0.0.json`](data/ataques-2.0.0.json) y
[`data/ataques-2.0.1.json`](data/ataques-2.0.1.json).

Gravedad: ninguno permite instalar ni arrancar nada sin firma (eso ya lo impedía la 2.0.0). Son
fallos de denegación de servicio (memoria, caídas del cliente, bloqueo del Update Center),
de integridad de descargas que luego la firma habría rechazado, de suplantación de DNS
(afecta a todo el sistema, no solo a UC) y la congelación.

Además, durante el desarrollo el propio banco encontró un fallo **en el arreglo**: la primera
versión de la comprobación post-handshake de TLS miraba el tamaño después de esperar los datos.
Corregido antes de entregar; lo cubre `test_tls_hardening`.

## 3. Sello de tiempo (contra la congelación)

Lo que garantiza:

- Si el servidor sirve el sello vigente, no puede esconder la última versión ni cambiar su
  manifiesto: `uc buscar` se para con «posible ataque de congelación».
- Un sello más viejo que uno ya visto no cuenta (se guarda la fecha del último en
  `/var/lib/uc/online`).
- Las claves de sello están dentro del volumen de sistema verificado y solo sirven para decir
  «esto es lo último»: no pueden firmar una versión. Si una se filtra, lo peor que permite es
  congelar las máquinas hasta la versión siguiente, que traiga otra.

Lo que **no** garantiza (dicho claro, igual que TUF):

- Un servidor que esconde también el sello solo provoca un aviso («sin confirmar»).
- Un servidor puede servir un sello viejo que no haya caducado: congelación de 35 días como
  mucho, y solo si la máquina no ha visto ya uno más nuevo.
- Si el propietario no renueva el sello en 35 días, todas las máquinas muestran «sin confirmar».

## 4. Lo que se revisó y no tenía fallos

- **Syscalls `update_*` y capacidades:** fuzzer con estado nuevo (`test_update_fuzz`), que llama
  a las syscalls a través de la capa real con `update.stage`: secuencias hostiles de
  `update_begin/write/commit/abort/activate` con nombres, tamaños y órdenes inválidos. Invariante:
  el conjunto A (el que arranca) no cambia nunca, byte a byte. Sin fallos.
- **A/B y cortes de luz:** las pruebas de corte en cada escritura de la 2.0.0 (T-UC-4, T-UC-23)
  siguen pasando con la 2.0.1.
- **Firmas de manifiestos y registros de claves:** sin cambios; los analizadores ya eran
  estrictos (ver el informe de la 2.0.0).

## 4b. La actualización 2.0.0 → 2.0.1 de punta a punta

Con los **artefactos del kit de publicación** (no con imágenes de prueba hechas a mano) y claves
desechables: imagen 2.0.0 construida por el kit de la 2.0.0, y Release 2.0.1 construida por
`construir_release.py` con los parámetros de la publicación. `verificar_release.py --con-uc
--sello --anterior` la da por buena (el cargador es byte a byte el de la 2.0.0). Después, en
QEMU + OVMF, lo mismo que `PRUEBA_AB.md` de la entrega
([`data/ab-qemu.json`](data/ab-qemu.json)):

| Paso | Resultado |
|---|---|
| 2.0.0 importa el `.ucb` de la 2.0.1 | Preparada en el conjunto B |
| 3 arranques de prueba apagados a lo bruto antes de confirmar | El cuarto arranca la 2.0.0 sola, conjunto B `mala`, `/etc` restaurado |
| Importar otra vez y dejarla arrancar | `actualización confirmada: PyOS 2.0.1` |
| `uc volver` | Negado por anti-retroceso, con el motivo |
| Reiniciar | Sigue la 2.0.1 |

9 de 9 comprobaciones, 8 minutos. Lo que no cubre: la consulta a GitHub real (`uc buscar` y el
sello en línea); eso lo prueba el propietario después de publicar.

Hallazgo de paso, **no de seguridad** y fuera de esta versión: `wget` de PyOS falla con un
`OverflowError` sin controlar al bajar más de ~1 MB (convierte todo el cuerpo de una vez y choca
con el límite de elementos por instrucción de la PVM). También está en la 2.0.0. Es un arreglo de
tipo P: va a la 2.1.0.

## 5. Pruebas

| Prueba | Qué cubre |
|---|---|
| `tests/secbench201.py` | Los 14 ataques de §2 contra cualquier árbol |
| `test_uctime` | Formato, firma, fechas, canal y anti-retroceso del sello; de extremo a extremo (PyOS en la máquina emulada contra un GitHub falso por TLS) que esconde la versión, cambia el manifiesto, o sirve un sello caducado, de otra clave o ninguno |
| `test_https_hardening` | URL, redirecciones, `chunked`, reanudación, cifras ASCII, `Retry-After` |
| `test_tls_hardening`, `test_x509_hardening` | Orden del handshake, tamaños, extensiones críticas |
| `test_dns` | Respuestas suplantadas (otra IP, otro puerto, otra pregunta) |
| `test_update_fuzz` | Fuzzer con estado de las syscalls de actualización |
| `test_release_kit` | Assets del Update Center y sello comprobados contra una imagen real |

## 6. Límites conocidos

Siguen los de la 2.0.0 (§6 de [su informe](../v2.0.0/README.md)), salvo la congelación, que
pasa a estar acotada como dice §3. No se ha probado contra el GitHub real desde este entorno
(sale por un proxy que intercepta TLS): lo hace el propietario al publicar.

Ningún arreglo se ha llevado a la rama 1.x. El fallo de DNS es del kernel y probablemente también
está en la 1.0.2 (no se ha comprobado contra `v1.0.2`).
