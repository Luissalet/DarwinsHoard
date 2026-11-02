# Ingesta y evidencia de entregas

`darwin_ingest.ingest_batch(store, records, channel=...)` conserva capturas por `capture_key` estable. Extrae referencias y las enlaza al catálogo sin afirmar verificación GitHub. Los candidatos `owner/repo` conservan su incertidumbre. Links y OCR pueden usar el mismo contrato; los conectores de origen deben aportar la identidad de cada aparición.

`sync_whatsapp_page(store, client, account=..., chat=..., limit=200)` consume una página del puente Faustus de la tarea 1868. `client(chat=..., cursor=..., limit=...)` devuelve `messages`, `next_cursor`, `has_more` y `coverage`. Sólo acepta mensajes del chat indicado por JID. Conserva mensajes propios, texto íntegro recibido, adjuntos y revisiones. No marca mensajes como leídos ni envía nada.

Se escribe cada captura antes del cursor. Una caída reintenta con las mismas claves, incluidas las operaciones de enlace pendientes. Al terminar una pasada, la siguiente empieza desde el principio para detectar ediciones y mensajes tardíos; los ya registrados no generan otra captura. Una edición crea otra revisión con la misma procedencia. El cursor no es una instantánea inmutable. Debe serializarse la ejecución de cada cuenta/chat en el coordinador; no lanzar dos sincronizaciones concurrentes del mismo chat.

La cobertura es el almacén retenido del puente, con su límite de retención, no todo el historial del teléfono. Los textos antiguos que el puente ya recortó no se recuperan por cambiar su lector. El backfill del teléfono y la descarga de adjuntos siguen dependiendo del puente; una referencia de adjunto no acredita su descarga ni su OCR.

`verify_deliveries(store, repo_roots)` comprueba sólo repos locales mapeados explícitamente. Busca la rama main/master y demuestra ancestría contra esa rama, incluso si el checkout está en otra. No ejecuta fetch, checkout ni programas del repo. Actualiza evidencia e implantación de esa entrega cuando el commit está integrado; mantiene la verificación funcional aparte y conserva entregas sustituidas. Un commit ausente o fuera de main se informa; no reescribe automáticamente una integración histórica tras un cambio de historia.

Pendiente de la entrega conjunta: conectar estas funciones a API/MCP/UI, revisión independiente y pruebas del recorrido completo. El paquete no arranca servicios ni importa datos reales por su cuenta.
