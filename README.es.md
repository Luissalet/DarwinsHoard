# Darwin's Hoard

Guarda cada hallazgo que podría mejorar Faustus o algún Hoard (un repo de GitHub, un artículo, un paper, un reel, una idea suelta) con su origen, qué se propuso y para qué app, qué se entregó, y el árbol de capacidades de toda la familia. Responde dos preguntas antes de gastar tiempo en un enlace: *¿esto ya lo vimos y qué pasó con ello?* y *¿qué app hace ya esto?*

Puerto **5233**, id `darwin`. Forma parte de la familia Hoard: copiloto de Faustus, ventana en el Hoard Hub y puente MCP.

## Pestañas

**Pregunta a Darwin** (en Resumen): una pregunta en lenguaje natural que responde el modelo local de la familia a partir del árbol, los hallazgos y las carencias, citando cada hallazgo por su número.

- **Resumen**: muestra
  - recuentos y hallazgos por estado;
  - las apps con más propuestas y de dónde vienen los hallazgos;
  - las entregas, declaradas y comprobadas en la rama principal;
  - la sincronización del chat Gittrend;
  - las importaciones, con el hash de cada fichero.
- **Historial**: todos los hallazgos.
  - Se filtran por texto, `owner/repo`, URL o número de radar, estado, app, origen y marcados con 📌, y se pueden ordenar.
  - Cada hallazgo abre su genealogía: apariciones con fichero y línea, propuestas por app con su historial, y entregas con commits, indicando si el commit está en main.
  - El estado agregado cuenta por propuesta (app o capacidad de una app), no por app: si hay dos capacidades propuestas para la misma app y solo una tiene entrega integrada, el hallazgo sale «mixta», no «integrada».
  - Desde ahí se cambian estados y se crean propuestas. «Debatir en el Ágora» abre un hilo por propuesta con su genealogía y muestra los mensajes en la ficha. «Proponer apps (IA)» hace que el modelo local proponga app para los hallazgos sin propuesta: quedan pendientes y nunca pisan tus decisiones.
- **Historial: filtros guardados y cobertura**. «Guardar filtro» guarda la búsqueda, el estado, la app, el origen, el orden y 📌 con un nombre que reutilizan la lista, `darwin_find` (`saved`) y los agentes. En la ficha, «¿Ya lo cubre alguna app?» compara sus palabras con el árbol: *ya cubierto*, *cubierto en parte* o *nadie lo hace*, con las apps y nodos que coinciden. Explica, nunca bloquea. `?open=<id>` abre un hallazgo y `?app=<id>` filtra por app.
- **Propuestas**: todas las propuestas en una lista, filtrable por estado, app, origen y palabras, con recuento por estado. El estado se cambia desde la fila.
- **Investigaciones**:
  - **Radar por carencias**: las carencias abiertas ordenadas por lo que ayudaría buscarlas, cada una con su búsqueda de GitHub y web (palabras clave en inglés que escribe una vez el modelo local y se guardan por carencia), los hallazgos que quizá ya la responden y si el árbol quizá ya la cubre. «Buscar en GitHub» lanza las tres primeras (o una con «Buscar esta»), descarta las listas de enlaces, dice qué repos ya conocía Darwin y, con «Guardar los repos nuevos», los registra.
  - **Preguntas guardadas** («avísame cuando…»): se repiten cada cuatro horas y solo avisan cuando aparecen hallazgos, cambios de estado o apps nuevos, con una notificación de la familia.
  - Una tarea programada llama a `darwin_radar_plan` o `darwin_watches_check` y calla cuando `notify` es falso.
- **Panel en Faustus**: la portada de cada proyecto de Faustus muestra una tarjeta de Darwin para el Hoard del proyecto (Research y ecosystem: toda la familia y las siguientes búsquedas del radar), leída a través del Hub (`GET /api/hoard/darwin/panel`). La página de Darwin enseña lo mismo con `?embed=panel&space=…&project=…`.
- **Bandeja**: capturas sin fuente todavía, con la imagen y el texto que leyó el OCR. Nunca se pierden; un clic las convierte en hallazgo. «Leer capturas (OCR)» lee los pantallazos con el OCR de la familia (el de Kafka) y enlaza las URL y los `owner/repo` que GitHub confirma; también se lanza solo tras sincronizar el chat.
- **Árbol**: Faustus (raíz) > Hoard Hub > Hoards > módulos absorbidos > capacidades > herramientas reales.
  - Cada nodo indica su evidencia (*declarada*, *viva*) y su estado (*disponible*, *detenida*).
  - El buscador «¿Quién hace…?» dice qué apps cubren ya algo y su ruta en el árbol. Lo que una descripción niega («Does not perform OCR…») no cuenta como coincidencia.
- **Cuentas para leer posts** (en Resumen): conectas X, Instagram, Threads, TikTok, Reddit, Facebook o YouTube; se abre una ventana de Links en tu ordenador y entras tú, sin que la contraseña pase por Darwin. «Leer posts» lee los tuits y posts enlazados y convierte en hallazgos los repos y enlaces que contienen. Si un sitio no deja leer, se para y te dice qué cuenta conectar.
- **Puntuación**: cada hallazgo abierto tiene una nota de 0 a 100 con sus motivos (encaja con una carencia, reaparece, estrellas, licencia, novedad, es un repo concreto). Historial ordena por ella con «Más interesantes».
- **Brain de Faustus**: Darwin escribe notas enlazadas en `Notes/Darwin/` del Brain (índice, una por app y una por hallazgo vivo) cada pocas horas o con `darwin_brain_export`; solo reescribe sus propias notas.
- **Novedades**: lo nuevo desde la última visita, o del último día, semana o mes.
- **Trajes**: la biblioteca de trajes, configuraciones de trabajo reutilizables para un tipo de encargo (objetivo, entradas con su identidad, conceptos del dominio, operaciones que usa, vistas, criterios de aceptación, receta y puntos donde hace falta juicio del modelo). Responde a «¿qué encargos sabes resolver?» con el estado de cada uno: `proposed` (propuesto), `partial` (respaldo parcial: faltan capacidades), `backed` (respaldado: toda operación necesaria existe en el árbol y está marcada como implementada **con prueba**) y `evaluated` (hay resultados importados de Pygmalion's Hoard). Un nombre de capacidad no basta: la prueba es un commit, un test o un fichero de QA (`darwin_capability_mark`; sin prueba se rechaza). Se siembran seis trajes de la propuesta 36 de la investigación; ninguno empieza respaldado.
- **Carencias, conciliadas**: una carencia que el árbol actual ya responde (capacidad implementada con prueba) se marca «posiblemente obsoleta» con su prueba y deja de contarse como abierta, pero no se cierra sola: la confirmas o la descartas tú. `darwin_gaps_reconcile` recalcula las marcas (también tras cada marcado y cada refresco del árbol). Con `semantic: true` el modelo local compara además las carencias abiertas con las capacidades respaldadas de todo el árbol, por significado y de cualquier app, y marca las que ve respondidas como «posiblemente obsoletas» con motivo `semantic`; nunca cierra una carencia, y la marca desaparece sola si la capacidad deja de estar respaldada.
- **Carencias desde los diarios de objetivos**: los `OBJETIVOS.md` de Faustus y Writer son diarios largos. `darwin_gaps_import` (también lo ejecuta `darwin_import_legacy`) los lee con una heurística de secciones y señales («pendiente», «falta», casillas sin marcar) y el modelo local, que se queda solo con lo que falta por hacer. Cada carencia guarda su origen (fichero, sección, línea); la importación es idempotente (no duplica, mueve la que cambió de línea y cierra la que salió del fichero) y añade como mucho 60 por pasada; `log_pending` dice cuántas quedan para la siguiente.
- **Corregir una entrega**: `darwin_delivery_fix` (`POST /api/deliveries/{id}/fix`) cambia el repositorio, el commit o la tarea del Ágora de una entrega, guarda lo declarado antes en `declared.declared_before_fix`, deja una fila en el historial y la vuelve a comprobar. `clear_commit` quita un commit que nunca existió; las que no se pueden probar siguen con su motivo.
- **Carencias**: lo que se quiere y ninguna app hace todavía. Se alimenta de los OBJETIVOS.md de cada Hoard que sean una lista; cuando un objetivo sale del fichero, su carencia se cierra.

El botón **Añadir** acepta una URL, `owner/repo` o texto libre. Si el hallazgo ya existe, devuelve la ficha existente.

## Modelo

captura → fuente → idea → propuesta (idea × app) → entrega (repo/commit/tarea del Ágora) → evidencia.

Una tarea del Ágora abierta para una propuesta la lleva en el título, «… (Darwin 1013)» o «(Darwin 1016, 1046)». La importación del Ágora (`darwin_import_legacy`) enlaza la tarea con cada propuesta que nombra y, cuando la tarea está `done` con commits, registra cada commit como entrega de esa propuesta.

Los estados de propuesta, implementación, verificación y operación van por separado. Lo declarado se guarda tal cual. La comprobación de commits añade `evidence.commit_ancestry` sin pisar lo declarado. Un commit en main es evidencia de código, no una prueba funcional. Todo cambio de estado queda en el historial.

## Comprobar entregas y mapa de repositorios

**Comprobar entregas** (`darwin_verify_deliveries`, solo git local, sin fetch) prueba cada entrega por orden de fuerza y `via` dice cómo:

- `direct`: el commit está en main del repositorio que nombra la entrega. Los nombres antiguos pasan por el **Mapa de repositorios** (Resumen; `darwin_repo_aliases`, `darwin_repo_alias_set`, `GET|POST /api/repo-aliases`): repos renombrados, el antiguo `D:\LocalAI` (se busca en todos), espacios del Ágora (Blood Arrows) y apps fusionadas en otra como subcarpeta (Galton → Pygmalion, Funes/Argus/Disk Hoard → Talos, Midas → Coase, Borges → Writer's, Tantalus/Phileas → Hermes, Babel/Theseus → Vitruvius, Gulliver → Vulcan, Laplace → Nightingale). Tus alias se guardan en el ajuste `repo_aliases` y mandan sobre los integrados.
- `other_repository`: tarea de varios repos declarada con un solo nombre; el commit está en main de otro repo local.
- `cherry_pick_trailer`: un commit de main dice «cherry picked from commit <id>».
- `patch_id` / `subject_date`: el commit existe (otra rama, objeto huérfano tras reescribir la historia) y main tiene uno equivalente: mismo `git patch-id --stable`, o mismo asunto y fecha de autor. `equivalent_of` guarda el declarado.
- `agora_resolution` / `agora_submission` / `agora_task`: el commit ya no existe y la tarea del Ágora dice qué llegó a main («Integrado en master (sha)», «viejo -> nuevo» tras un cherry-pick, la línea «Commits:» de la última entrega, los commits de la tarea) y eso está en main. Una línea del tracker sin commit («✅ hecho (#527)») usa las tareas que cita; si cita una sola, se apunta en la entrega.
- `imported` (`history_not_imported`): el código llegó con una app fusionada sin su historia; se indica la carpeta, el commit que la añadió y el commit de origen de `provenance/`. El commit declarado no se puede comprobar en local y la implementación se queda como estaba declarada.
- Si no, `not_in_main` o `unknown` con el motivo (`commit_not_found`, `no_commit_declared`, `invalid_commit_id`, `repository_not_mapped`, `repository_unavailable`).

## Trajes: herramientas y rutas

`darwin_suits`, `darwin_suit_get`, `darwin_suit_save`, `darwin_suit_delete`, `darwin_suits_seed`, `darwin_capability_mark`, `darwin_gaps_reconcile`, `darwin_gaps_import`, `darwin_delivery_fix`, `darwin_suit_import_eval`. REST: `GET /api/suits`, `GET|PUT|DELETE /api/suits/{slug}`, `POST /api/suits/{slug}/evaluation`, `POST /api/evaluations`, `POST /api/capabilities/mark`, `GET /api/gaps`, `POST /api/gaps/reconcile`, `POST /api/gaps/import`, `POST /api/deliveries/{id}/fix`. Una evaluación se rechaza si no tiene ningún caso puntuado; los casos usados para construir la mejora llegan excluidos y se muestran aparte.

## Investigaciones: herramientas y rutas

`darwin_coverage`, `darwin_radar_plan`, `darwin_radar_run`, `darwin_watch_add`, `darwin_watches`, `darwin_watches_check`, `darwin_watch_update`, `darwin_proposals`, `darwin_saved_filters`, `darwin_panel`. REST: `GET /api/coverage`, `GET /api/radar/plan`, `POST /api/radar/run` (con `web: true` busca también en la web sin clave, la página HTML de DuckDuckGo como Faustus, y muestra o guarda las páginas), `GET|POST /api/watches`, `POST /api/watches/check`, `PATCH|DELETE /api/watches/{id}`, `GET /api/proposals`, `GET /api/filters`, `PUT|DELETE /api/filters/{nombre}`, `GET /api/panel`.

## Orígenes

- **Ficheros del radar** (`RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md`, `radar-ideas.md`). La importación es idempotente.
- **Tareas del Ágora** que citan `radar #N`.
- **Chat de WhatsApp «Gittrend»**, en solo lectura a través del puente de Faustus y paginado por cursor. No envía nada ni marca nada como leído. Si el puente está parado, la sincronización lo arranca a través de Faustus, espera a que conecte y vuelve a leer. Cuando el Hub ha movido Faustus a una Spark («Ejecutar en»), Darwin le pregunta a ese Faustus, porque la sesión de WhatsApp viaja con él.
- **Links**: lo que guardes en Links con la etiqueta `darwin` y cualquier repositorio de GitHub guardado allí (cada pocas horas o con `darwin_import_links`).
- **Otras apps y agentes**, vía `darwin_ingest` y `darwin_add`.
- **Árbol**: se construye con `/api/apps` del Hub, el catálogo de herramientas de Faustus y los manifiestos.

## Arrancar

`Iniciar Darwin's Hoard.cmd`, o desde el Hoard Hub. Datos en `data/darwin.db` y ajustes en `data/settings.json`.

El puente MCP (`mcp_server.py`) nunca arranca la app: con Darwin parado lista las herramientas del propio paquete y una llamada responde `not_running`. Se arranca a propósito desde el Hoard Hub (Iniciar en su tarjeta o `POST http://127.0.0.1:8810/api/apps/darwin/start`), con `Iniciar Darwin's Hoard.cmd` o con `python -m darwin_hoard`.

## Pruebas

`.venv\Scripts\python.exe -m pytest`
