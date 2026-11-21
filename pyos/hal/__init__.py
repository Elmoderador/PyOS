"""Capa de abstracción de hardware (HAL) de PyOS.

Dos implementaciones con la misma interfaz:
  - hal.uefi:     hardware REAL de la máquina (puertos de E/S, ACPI, PS/2, UART,
                  RAM física), usado cuando PyOS arranca directamente sobre UEFI.
  - hal.emulated: máquina emulada en el proceso host (desarrollo y tests).

Interfaz de una Machine:
  ram        .size .read(a,n) .write(a,data) .fill(a,n,v) .read_u32(a) .write_u32(a,v) .find_byte(v,s,e)
  clock()    segundos monotónicos (float, alta resolución)
  wall()     hora de reloj (epoch)
  disk       .sectors .read(lba,n) .write(lba,data) .flush()
  console    .write(bytes)   salida de pantalla
  uart       .present .has_data() .read_byte() .write(bytes)   (puede no existir)
  kbd        .present .read_scancode() -> int | None              (PS/2 set 1)
  power_button_pressed() -> bool (y lo rearma)
  power_off() / reset()
  info()     dict con datos de plataforma para /proc
  idle()     espera breve cuando la CPU no tiene trabajo
"""
import sys


def is_uefi():
    return sys.platform == "uefi"


class MachineCheck(Exception):
    """Error de hardware."""
