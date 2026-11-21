# Contribuir a PyOS

Gracias por tu interés. Unas pocas reglas:

## La regla del proyecto

Todo en Python. **Si se puede importar desde Python, está permitido**; no se escribe C, C++,
Rust ni ensamblador directamente. Lo que haga un driver tiene que ser real (nada simulado
para aparentar), y sus límites se documentan en `docs/LIMITATIONS.md`.

## Antes de abrir un pull request

```sh
python -m pip install pytest
python -m pytest                 # toda la batería (máquina emulada, sin VM)
python tests/look_fuzz.py 1 80   # opcional: fuzzer de LOOK, si tocas el entorno gráfico
```

Si tocas el arranque UEFI, los drivers reales o LOOK, prueba también en QEMU + OVMF:

```sh
python -m pyos.tools.mkuefi build/uefi
python tests/uefi_smoke.py build/uefi/pyos-uefi.img
```

- Un cambio, un pull request, con tests para lo que añade o arregla.
- Código y textos de la interfaz en español; mensajes claros para quien no es experto.
- Si rompes `LOOK_API` o reutilizas el comportamiento de una syscall, dilo en el PR: obliga a
  subir el número U y a marcarlo como cambio incompatible en el CHANGELOG.

## Licencia

Al contribuir aceptas que tu aportación se publique bajo la licencia Apache-2.0 del proyecto.
