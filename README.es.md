# Darwin's Hoard

Guarda cada hallazgo que podría mejorar Faustus o algún Hoard (un repo de GitHub, un artículo, un paper, un reel, una idea suelta) con su origen, qué se propuso y para qué app, qué se entregó, y el árbol de capacidades de toda la familia. Responde dos preguntas antes de gastar tiempo en un enlace: *¿esto ya lo vimos y qué pasó con ello?* y *¿qué app hace ya esto?*

Puerto **5233**, id `darwin`. Forma parte de la familia Hoard: copiloto de Faustus, ventana en el Hoard Hub y puente MCP.

## Pestañas

- **Resumen**: muestra
  - recuentos y hallazgos por estado;
  - las apps con más propuestas y de dónde vienen los hallazgos;
  - las entregas, declaradas y comprobadas en la rama principal;
  - la sincronización del chat Gittrend;
  - las importaciones, con el hash de cada fichero.
- **Historial**: todos los hallazgos.
  - Se filtran por texto, `owner/repo`, URL o número de radar, estado, app, origen y marcados con 📌, y se pueden ordenar.
  - Cada hallazgo abre su genealogía: apariciones con fichero y línea, propuestas por app con su historial, y entregas con commits, indicando si el commit está en main.
  - Desde ahí se cambian estados y se crean propuestas.
- **Bandeja**: capturas sin fuente todavía, con la imagen y el texto que leyó el OCR. Nunca se pierden; un clic las convierte en hallazgo. «Leer capturas (OCR)» lee los pantallazos con el OCR de la familia (el de Kafka) y enlaza las URL y los `owner/repo` que GitHub confirma; también se lanza solo tras sincronizar el chat.
- **Árbol**: Faustus (raíz) > Hoard Hub > Hoards > módulos absorbidos > capacidades > herramientas reales.
  - Cada nodo indica su evidencia (*declarada*, *viva*) y su estado (*disponible*, *detenida*).
  - El buscador «¿Quién hace…?» dice qué apps cubren ya algo y su ruta en el árbol.
- **Novedades**: lo nuevo desde la última visita, o del último día, semana o mes.
- **Carencias**: lo que se quiere y ninguna app hace todavía.

El botón **Añadir** acepta una URL, `owner/repo` o texto libre. Si el hallazgo ya existe, devuelve la ficha existente.

## Modelo

captura → fuente → idea → propuesta (idea × app) → entrega (repo/commit/tarea del Ágora) → evidencia.

Los estados de propuesta, implementación, verificación y operación van por separado. Lo declarado se guarda tal cual. La comprobación de commits añade `evidence.commit_ancestry` sin pisar lo declarado. Un commit en main es evidencia de código, no una prueba funcional. Todo cambio de estado queda en el historial.

## Orígenes

- **Ficheros del radar** (`RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md`, `radar-ideas.md`). La importación es idempotente.
- **Tareas del Ágora** que citan `radar #N`.
- **Chat de WhatsApp «Gittrend»**, en solo lectura a través del puente de Faustus y paginado por cursor. No envía nada ni marca nada como leído.
- **Otras apps y agentes**, vía `darwin_ingest` y `darwin_add`.
- **Árbol**: se construye con `/api/apps` del Hub, el catálogo de herramientas de Faustus y los manifiestos.

## Arrancar

`Iniciar Darwin's Hoard.cmd`, o desde el Hoard Hub. Datos en `data/darwin.db` y ajustes en `data/settings.json`.

## Pruebas

`.venv\Scripts\python.exe -m pytest`
