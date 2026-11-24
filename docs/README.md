# 📚 Documentación del repositorio

Aquí solo hay **informes de seguridad**, con pruebas medidas. La documentación técnica de PyOS (`ARCHITECTURE.md`, `VM.md`, `NET.md`, `LOOK.md`, `LIMITATIONS.md`…) va dentro del `.zip` de cada [Release](https://github.com/Elmoderador/PyOS/releases).

## 🛡️ Informes de seguridad

Cada versión de seguridad (la **S** de U.P.S.) trae un informe que lanza los mismos ataques contra la versión anterior y contra la nueva, y compara los resultados.

| Versión | Fecha | Resultado | Informe |
|---|---|---|---|
| **v2.0.0** | 2026-11-23 | Modelo de confianza del Update Center: firmas, arranque A/B, verity y qué puede hacer un servidor malicioso | [security/v2.0.0](security/v2.0.0/) |
| **v1.0.2** | 2026-11-22 | Cuotas de CPU y memoria, `httpd` concurrente, fuzzer de red con estado | [security/v1.0.2](security/v1.0.2/) |
| **v1.0.1** | 2026-11-21 | 13 de 13 escenarios de ataque cerrados | [security/v1.0.1](security/v1.0.1/) |

Para informar de una vulnerabilidad, mira [SECURITY.md](../SECURITY.md).
