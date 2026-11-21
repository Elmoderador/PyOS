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
vulnerabilidades nuevas porque están documentados en [docs/LIMITATIONS.md](docs/LIMITATIONS.md):
no hay usuarios ni permisos, todo se ejecuta como un único usuario, y la red no tiene TLS.

Sí son vulnerabilidades, por ejemplo: que un programa de usuario escape del aislamiento de la
PVM y ejecute Python del anfitrión, que lea o escriba memoria del kernel, o que un paquete de
red malformado haga caer el kernel.
