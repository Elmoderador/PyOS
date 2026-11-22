# Seguridad

## Versiones con soporte

Solo la última versión U.P recibe arreglos de seguridad (el número S de U.P.S, ver
[CHANGELOG.md](CHANGELOG.md)).

## Informar de una vulnerabilidad

No abras un issue público. Usa **"Report a vulnerability"** en la pestaña *Security* del
repositorio (GitHub Private Vulnerability Reporting). Incluye:

- versión de PyOS (`pyos` en PyOS Term o la ventana *Acerca de* de LOOK),
- qué permite hacer el fallo y cómo reproducirlo,
- si lo has probado en QEMU, VirtualBox, VMware o en la máquina emulada de los tests.

## Alcance

PyOS es un proyecto experimental y educativo. Hay límites conocidos que **no** son
vulnerabilidades nuevas porque están documentados en `docs/LIMITATIONS.md` (en el `.zip` de cada Release):
no hay usuarios ni permisos, todo se ejecuta como un único usuario, y la red no tiene TLS.

Tampoco lo son, de momento, estos límites conocidos:

- **Las cuotas de memoria se comprueban, no se garantizan al byte.** Las reservas grandes se
  rechazan antes de hacerse, pero lo que un proceso acumula poco a poco se mide entre rodajas:
  puede pasarse de su cuota durante un momento (lo que cree hasta la siguiente medida) antes de
  recibir SIGKILL. Los búferes del kernel (sockets, tuberías, pantalla) no cuentan en la cuota
  del proceso; tienen sus propios topes.
- **Coste por instrucción acotado, no nulo.** Ninguna instrucción de la PVM deja al planificador
  sin control más de ~0,2 s en CPython 3.6 nativo (más en máquinas lentas o emuladas): un
  proceso puede seguir causando pausas cortas repetidas. Sin `ulimit -t`, un proceso puede usar
  toda su parte de CPU indefinidamente (el planificador reparte por turnos).
- **`httpd` atiende 32 conexiones a la vez.** Con más, expulsa a la más antigua que no ha
  terminado su petición: un atacante con muchas conexiones puede expulsar a un cliente legítimo
  que sea lento, aunque ya no puede retrasar a los que envían su petición a tiempo.
- **Las aplicaciones de LOOK** (`/usr/share/look/apps`) se ejecutan dentro del proceso de LOOK,
  con sus mismos permisos: instala solo las que conozcas.

Sí son vulnerabilidades, por ejemplo: que un programa de usuario escape del aislamiento de la
PVM y ejecute Python del anfitrión, que lea o escriba memoria del kernel, que un paquete de
red malformado haga caer el kernel, o que una sola instrucción de la PVM deje al planificador
sin control durante segundos o que un proceso agote la memoria de todo el sistema.
