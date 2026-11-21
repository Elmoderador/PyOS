# PyOS en una máquina virtual (sin Linux)

Usa el **disco** que corresponda a tu hipervisor. No hay ISO: PyOS necesita una
partición FAT con escritura para guardar tus datos.

## VirtualBox (`pyos-v1.0.0.vdi`)
1. Nueva máquina: nombre `PyOS`, tipo **Other**, versión **Other/Unknown (64-bit)**.
   Sirve también "Other Linux (64-bit)".
2. **No** selecciones ninguna ISO y marca *Skip Unattended Installation* si aparece.
3. Hardware: 512 MB de RAM, 1 CPU, **Enable EFI** marcado.
4. Disco duro: **Use an Existing Virtual Hard Disk File** → `pyos-v1.0.0.vdi`.
5. Arranca la VM.

Por PowerShell (con la VM apagada y el `.vdi` en Descargas):
```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb createvm --name PyOS --ostype Other_64 --register
& $vb modifyvm PyOS --memory 512 --firmware efi64 --ioapic on --cpuexecutioncap 30 `
      --graphicscontroller vboxsvga --vram 32 --mouse ps2 --keyboard ps2 `
      --nic1 nat --nictype1 82540EM
& $vb storagectl PyOS --name SATA --add sata --controller IntelAhci
& $vb storageattach PyOS --storagectl SATA --port 0 --device 0 --type hdd --medium "$env:USERPROFILE\Downloads\pyos-v1.0.0.vdi"
& $vb startvm PyOS
```

Para PyOS LOOK: controlador gráfico **VBoxSVGA** (o VBoxVGA) y ratón **PS/2**
(`--graphicscontroller vboxsvga --mouse ps2`). Con VMSVGA o "tableta USB" la parte
gráfica puede no funcionar; PyOS Term funciona igual.

Para la red: adaptador 1 en **NAT**, tipo **Intel PRO/1000 MT Desktop (82540EM)**
(`--nic1 nat --nictype1 82540EM`). Ver [`NET.md`](NET.md).

### Actualizar a una versión nueva
Cada versión trae su propio disco (`pyos-vU.P.S.vdi`) con un UUID distinto. Con la VM apagada,
cambia el disco por el nuevo (en este ejemplo, la 1.1.0):
```powershell
& $vb storageattach PyOS --storagectl SATA --port 0 --device 0 --medium none
& $vb storageattach PyOS --storagectl SATA --port 0 --device 0 --type hdd --medium "$env:USERPROFILE\Downloads\pyos-v1.1.0.vdi"
```
Si VirtualBox se queja de que *el UUID no coincide con el registrado*, es porque has
sobrescrito un `.vdi` con otro del mismo nombre: guarda cada versión con su nombre propio
(o quita el viejo del gestor de medios: `& $vb closemedium disk "ruta\al.vdi"`).
El disco nuevo empieza limpio: tus archivos de la versión anterior siguen en el `.vdi` viejo.

## Hyper-V (`pyos-v1.0.0.vhdx`)
Generación **2** → Seguridad → desmarca **Habilitar arranque seguro** → conecta el `.vhdx`.

## VMware (`pyos-v1.0.0.vmdk`)
Otro → Other 64-bit, firmware **UEFI** sin Secure Boot, disco existente `.vmdk`.

## QEMU (`pyos-v1.0.0.img`)
```bash
qemu-system-x86_64 -m 512 -bios /usr/share/ovmf/OVMF.fd -drive file=pyos-v1.0.0.img,format=raw \
    -nic user,model=e1000
```

## Qué verás
1. El logo del firmware y el UEFI Shell, con una cuenta atrás de 5 segundos (pulsa
   cualquier tecla para saltarla).
2. "Buscando PyOS..." y luego "PyOS: iniciando máquina sobre UEFI".
3. Durante un instante, los banners del Shell: es PyOS pidiéndole al firmware que
   suelte el teclado y el puerto serie.
4. BIOS PyOS → **selector de arranque**. No arranca nada solo: elige con las flechas
   + Intro o con el número:
   - `1` PyOS LOOK, el entorno gráfico (ver [`LOOK.md`](LOOK.md))
   - `2` PyOS Term
   - `3…` las distribuciones Linux que encuentre en otros discos
5. bootloader (SHA-256 OK) → mensajes del kernel → logo → `root@pyos:/root#`.

## Añadir Linux (opcional)
Crea un segundo disco en la VM e instala en él Ubuntu, Arch o Kali **en modo UEFI**
(con la VM ya en EFI, el instalador lo hace solo). Deja el disco de PyOS como primero
en el orden de arranque. El selector mostrará la distribución; al elegirla arranca su
kernel Linux. Detalles y límites: [`ARCHITECTURE.md`](ARCHITECTURE.md).

VirtualBox, con la VM apagada:
```powershell
& $vb createmedium disk --filename "$env:USERPROFILE\VirtualBox VMs\PyOS\linux.vdi" --size 30000
& $vb storageattach PyOS --storagectl SATA --port 1 --device 0 --type hdd --medium "$env:USERPROFILE\VirtualBox VMs\PyOS\linux.vdi"
& $vb storageattach PyOS --storagectl SATA --port 2 --device 0 --type dvddrive --medium "$env:USERPROFILE\Downloads\ubuntu.iso"
```
Para instalar, arranca desde el DVD (F12 / tecla del menú de arranque de EFI o
pulsa una tecla en la cuenta atrás del Shell y escribe `exit` → Boot Manager). Al
terminar, quita el DVD.

## Teclas
| Tecla | Acción |
|---|---|
| Ctrl+C | Interrumpe el programa en primer plano |
| Ctrl+D | Fin de entrada (en la shell: apaga) |
| Ctrl+U | Borra la línea |
| Ctrl+Alt+Supr | Reinicio ordenado |
| Máquina → **Apagado ACPI** (VirtualBox) | Apagado ordenado por el botón de encendido ACPI |

## Prueba rápida
```
arcade                 # menú de juegos: snake, tetris, pong, breakout, invaders, 2048, minas
help
pyos                   # estado del sistema
pkg install juegos     # instala juegos (y su dependencia extras): tresenraya, adivina
svc list               # servicios
dev kbd us             # cambia la distribución de teclado
hwinfo                 # hardware real: CPU, temporizador ACPI, bus PCI
forktest               # fork() real con copia de memoria
sigtest                # manejadores de señales de usuario
sandbox                # 10 intentos de escape de la CPU virtual
spin 5 &               # bucle infinito: la shell sigue respondiendo
top                    # instrucciones ejecutadas por proceso
cat /proc/1/stack      # pila de llamadas de init dentro de la PVM
edit /root/hola.py     # escribe un programa (a, líneas, '.', wq) y ejecútalo: sh /root/hola.py
halt
```
Lo que guardes en `/root` o `/home` sigue ahí en el siguiente arranque.
