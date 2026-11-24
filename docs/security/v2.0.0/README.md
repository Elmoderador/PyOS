# Informe de seguridad — PyOS 2.0.0

Todas las cifras se han medido en local sobre el código de la 2.0.0.
Las claves usadas en las pruebas son desechables (E5); no se ha generado ni usado ninguna clave
real de publicación.

## 1. Superficie nueva respecto a 1.0.2

| Pieza | Qué protege | Dónde |
|---|---|---|
| Arranque A/B firmado (Ed25519) | Que solo arranque un kernel + sistema firmados por una clave de la cadena de confianza | `boot/bootloader.py`, `kernel/update/` |
| Volumen de sistema dm-verity | Que `/bin`, `/sbin`, `/lib`, `/usr` no se puedan alterar ni en uso ni con la máquina apagada | `kernel/fs/verity.py`, `volumes.py` |
| Almacén de claves con registros firmados | Rotación y revocación de claves de firma sin reinstalar | `kernel/update/trust.py` |
| Update Center (syscalls 101–109) | Instalar, confirmar y volver atrás sin dejar la máquina sin arranque | `kernel/update/manager.py`, `uc-lite`, `ucd` |
| Capacidades por proceso (D2) | Que el shell, LOOK y los programas del usuario no puedan llamar a `update.*`, `disk.raw`, etc. | `kernel/caps.py` |
| Paquetes firmados (PYOSPKG 2) | Que los paquetes del repositorio del sistema no se puedan suplantar | syscall 110, `sbin/pkg.py` |
| TLS 1.3 en Python puro | Confidencialidad e integridad de la consulta a GitHub (no de la decisión de instalar) | `lib/tls.py`, `lib/x509.py`, syscall 112 |

## 2. Modelo de confianza de UC

Lo único que decide si algo se instala es la **firma del manifiesto** con una clave del
almacén del sistema (UC-23), comprobada por el kernel en `update_begin` y otra vez por el
bootloader en cada arranque. TLS, el JSON de GitHub, los tamaños de los assets y `SHA256SUMS`
solo sirven para encontrar y traer bytes; un servidor malicioso (o `uc.api` cambiado, o una raíz
TLS añadida en `/etc/pyos/roots`) puede:

- negar actualizaciones o servir una lista vieja (**ataque de congelación**: no hay un rol de
  sello de tiempo tipo TUF; UC solo garantiza que nunca se instala una versión anterior a la
  instalada, por anti-retroceso y por fecha),
- gastar ancho de banda y espacio de la caché (acotados: cada asset, al tamaño que dice el
  manifiesto ya verificado; manifiesto, firmas, registros y changelog, a 64 KiB; respuestas JSON,
  a 2 MiB; y se comprueba el espacio libre antes de descargar),
- saber que la máquina consulta (privacidad).

No puede hacer instalar ni arrancar nada no firmado: lo comprueban `test_uc` (T-UC-2, 8, 9),
`test_uc_online` (UC-23: `SHA256SUMS` falso que no se usa) y los fuzzers de abajo.

Los registros de claves (`keyrec-N`) de una Release se aplican al **consultar**, antes de
instalar: están firmados por la clave raíz o la de recuperación y el kernel los verifica, así
que aplicarlos es seguro, pero `uc buscar` puede cambiar el almacén de claves (rotar o revocar
una clave) aunque el usuario no instale nada.

## 3. Fallos encontrados durante el desarrollo de la 2.0 (ya corregidos)

| Fallo | Gravedad | Cómo se encontró | Prueba que lo cubre |
|---|---|---|---|
| **Planificador (regresión de la rama 2.0):** el ejecutor solo sondeaba las interrupciones al agotarse el presupuesto de instrucciones; un proceso que encadenaba syscalls rápidas no lo agotaba nunca, así que no había temporizador ni expropiación mientras siguiera (bucle de `getpid()`: 4,7 s en el anfitrión; `uc importar`: 3,3 s en QEMU). Cualquier programa podía congelar el resto del sistema | **Alta**: denegación de servicio local | `tests/uefi_update.py` (hueco de 3,3 s sin ninguna syscall ni rodaja lenta) e instrumentación nueva de `/proc/latency` | `test_preempt_syscalls` (falla sin el arreglo: 5,7 s); no afecta a 1.0.1 (medido). Arreglo: cada syscall cuenta para el presupuesto de la rodaja y se sondea tras una syscall que tocó el disco |
| `tls.py`: un registro con el MAC incorrecto al final de la conexión se trataba como cierre limpio (la respuesta truncada o manipulada llegaba como vacía, sin error) | Media: integridad del último registro | `test_tls`, registro manipulado | `test_tls_ec_chain_wrong_host_untrusted_tampered` |
| `json.py`: un escape `\uD800\u:de0` lanzaba `ValueError` fuera de `JsonError` (el proceso moría) | Baja: DoS de `uc buscar` | fuzzer diferencial | `test_json_fuzz` |
| `json.py` aceptaba números no válidos (`+1`, `01`, `.5`) | Baja | fuzzer diferencial | `test_gramatica_estricta` |
| `x509.py`: fechas con bytes no ASCII lanzaban `UnicodeDecodeError` fuera de `X509Error` | Baja: DoS del cliente | fuzzer de certificados en PyOS | `test_fuzz_x509_solo_x509error` |
| `svcd`: un servicio esencial que arrancaba pero no respondía contaba como sano, así que `init` habría confirmado una actualización con `ucd` colgado | Media: una versión rota quedaba confirmada | T-UC-7 | `test_t_uc_7_ucd_nuevo_que_se_cuelga` |
| Shell: lo tecleado entre el prompt y el paso a modo crudo salía dos veces | Baja (cosmético) | Destapado por el arreglo del planificador | `test_lineedit`, `test_history`, `test_nice`, `test_look` |
| `eventd` lee los permisos del emisor al aceptar la conexión: un proceso que publicaba y salía en seguida perdía su aviso (`uc.*`) | Baja: avisos perdidos | T-UC-31 | `test_t_uc_31_*` (publicación con espera) |

## 4. Fallos que también tiene 1.0.2

Reproducidos contra `v1.0.2` y corregidos solo en esta rama (lista completa en
[`CHANGELOG.md`](../../../CHANGELOG.md), sección «Fallos que también tiene la 1.0.2»): inundación
de SYN, tabla ARP sin tope, DNS (puerto retenido, puerto de origen secuencial, caché sin tope,
etiquetas largas), `ping` sin dueño, plazos heredados, teclado PS/2, `lx_spawn` sin tope, reloj
UEFI que se atrasaba, límite de CPU esquivable tras syscalls largas, y compilación que congelaba
el sistema. **Decisión del propietario (E2):** si se publica una 1.0.3 con estos arreglos; no se
ha tocado la línea 1.x.

## 5. Pruebas de seguridad ejecutadas

| Prueba | Qué hace | Resultado |
|---|---|---|
| `sysfuzz` (batería) | Argumentos aleatorios a todas las syscalls desde PyOS | Sin pánicos ni excepciones fuera de errno |
| `test_json_fuzz` | 3 000 valores aleatorios contra `json` de CPython (3 formatos) + 20 000 mutaciones | Igual que CPython o `JsonError`; nunca otra excepción |
| `test_fuzz_x509_solo_x509error` | 1 500 certificados EC/RSA mutados, analizados dentro de PyOS | Solo `X509Error` |
| `test_fuzz_handshake_del_servidor` | 40 handshakes con un bit cambiado en el vuelo del servidor | Siempre `TLSError` |
| `test_tls` | Cadena EC y RSA contra OpenSSL; nombre ajeno; raíz no fiable; certificado caducado; registro manipulado | Todo rechazado con su motivo |
| `test_uc` (T-UC-2, 8, 9, 17, 25, 26) | Manifiestos manipulados, sin firma, firma ajena, canales, revocación y rotación, anti-retroceso | Rechazados |
| T-UC-4, T-UC-23 | Corte de luz en **cada** escritura de una actualización y del bootloader | Siempre arranca una versión buena |
| `test_caps`, T-UC-8 | Syscalls 102–109 desde el shell (sin `update.stage`) | `EPERM` |
| `test_pkgsig` | Paquetes sin firma o manipulados en el repositorio del sistema | Rechazados |

## 6. Límites conocidos (no son vulnerabilidades nuevas)

- **Criptografía en Python puro sin tiempo constante.** X25519, ChaCha20-Poly1305 y la
  verificación ECDSA/RSA usan enteros de Python. Las verificaciones solo manejan datos públicos;
  la clave efímera X25519 de cada conexión podría filtrarse por tiempos a un atacante que mida
  con precisión, y eso solo expondría esa sesión (que transporta datos públicos firmados).
- **TLS mínimo:** solo TLS 1.3, `TLS_CHACHA20_POLY1305_SHA256` y X25519 (es lo que ofrece el
  cliente; GitHub lo acepta). Sin reanudación de sesión, sin OCSP ni CRL (la revocación de
  certificados TLS no se comprueba), sin SNI cifrado.
- **Sin usuarios:** todo el que tiene la shell tiene las capacidades de usuario por defecto,
  que incluyen `config` (puede cambiar `uc.api`) y escribir en `/etc/pyos/roots`. Ver §2: no
  permite instalar nada no firmado.
- **Consultas sin autenticar a GitHub:** límite de la API (60 por hora y por IP). UC respeta
  `Retry-After`/`X-RateLimit-Reset` y consulta como mucho cada `uc.intervalo` (6 h).
- **Avisos de eventd:** los permisos del emisor se leen al aceptar la conexión; los emisores de
  vida corta deben usar `ev_publish_wait`. La solución completa (credenciales del par fijadas
  por el kernel al conectar) queda para una versión posterior.
- **Prueba contra GitHub real sin hacer aquí:** el entorno de desarrollo sale por un proxy que
  intercepta TLS. Se hace en el QA del propietario (`docs/INSTALAR_ACTUALIZAR_RECUPERAR.md` §7).
