# Pendientes

Requieren decisión o acción de Luis:

- **Conector de Faustus bloqueado por el pre-escaneo de seguridad.** Los ficheros vendorizados de Hoard Link (`browser_lane.py`, `family.py`, `_famsvc.py`) se marcan como EXFIL_SECRET_TO_NETWORK porque la lista `_HOARD_LINK_NAMES` de `src/security_scan.py` en Faustus no incluye «Hoard Hub» tras el renombrado. Opciones: aprobar la excepción en Faustus → Ajustes → Integraciones, o autorizar el cambio en `_HOARD_LINK_NAMES`. Mientras tanto Darwin funciona por el Hub y por su puente MCP.
- **Puente de WhatsApp sin vincular.** Hace falta escanear el QR en Faustus para que la sincronización de Gittrend lea mensajes.
- **Reiniciar Faustus (7000)** para que sirva `/api/whatsapp/message-page`.

Hallazgos para revisar:

- 28 entregas declaradas cuyo commit no está en main (26 en Faustus, 2 en Hoard Link) y 6 commits no encontrados: visibles en Resumen → Entregas y filtrables en Historial.
- 57 entregas sin comprobar: apps absorbidas sin repositorio propio.
