# Pendientes

Limitaciones conocidas y cosas que dependen de la instalación:

- **Conector de Faustus.** El pre-escaneo de seguridad de Faustus marca los ficheros vendorizados de Hoard Link (`browser_lane.py`, `family.py`, `_famsvc.py`) porque su lista de nombres de la familia no incluye «Hoard Hub» tras el renombrado. Mientras no se corrija en Faustus o se apruebe la excepción en Ajustes → Integraciones, Darwin funciona por el Hub y por su puente MCP.
- **Radar programado.** Las instrucciones para que un radar programado registre todo en Darwin están en `docs/RADAR.md`; hay que aplicarlas a la tarea programada.
- **Leer posts de X sin ventana.** La ventana de inicio de sesión de Links no admite «Continuar con Google» (Google rechaza navegadores controlados por una aplicación), así que la cuenta de X se conecta con usuario y contraseña de X. X puede limitar temporalmente ese inicio de sesión; mientras no haya sesión, los posts quedan pendientes sin marcarse y Darwin pide conectar la cuenta.
- **Triaje automático.** Propone sin saber si la app ya usa esa herramienta (p. ej. puede proponer para Links algo que Links ya integra): las propuestas con origen *agent* se revisan a mano en Historial.
- **Entregas sin prueba en main.** La comprobación de commits distingue las entregas cuyo commit no está en la rama principal, las que tienen un commit que no aparece y las de apps absorbidas sin repositorio propio; se revisan en Resumen → Entregas.
