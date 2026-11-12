# Darwin's Hoard

Aplicación local que guarda cada hallazgo que pueda mejorar Faustus o uno de los Hoards (un repositorio de GitHub, un artículo, un paper, un reel, una idea suelta) junto con su fuente, las propuestas hechas para cada app, lo entregado y el árbol de capacidades de toda la familia.

[Read in English](README.md)

## Qué es

Antes de gastar tiempo en un enlace, Darwin responde a dos preguntas: *¿esto ya lo hemos visto y qué pasó con ello?* y *¿qué app ya hace esto?* Un hallazgo se sigue desde su captura hasta su evidencia:

captura → fuente → idea → propuesta (idea × app) → entrega (propuesta × repositorio/commit/tarea) → evidencia.

Los ejes de estado se mantienen separados y nunca se funden en una sola marca:

- propuesta: `pendiente`, `investigando`, `debatida`, `aceptada`, `aplazada`, `descartada`, `cubierta`;
- implementación por entrega: `sin_implementar`, `parcial`, `integrada`, `sustituida`;
- verificación por entrega: `documentada`, `probada`, `recomprobar`, `desconocida`;
- operación por nodo del árbol: `disponible`, `detenida`, `desconocida`.

Lo que declara un documento o una persona se guarda tal cual; las comprobaciones añaden evidencia al lado sin sobrescribirlo. Cada cambio de estado conserva el valor anterior en un historial.

Forma parte de la familia Hoard (copiloto Faustus, ventana del Hoard Hub, puente MCP). Puerto **5233**, id `darwin`.

## Qué hace

**Hallazgos**
- **Historial**: todos los hallazgos, filtrables por texto, `owner/repo`, URL o número de radar, estado, app, origen y marcados con 📌, en varios órdenes. Cada uno abre su genealogía: apariciones con fichero y línea, propuestas por app con su historial, entregas con commits y si cada commit está en la rama principal.
- Caja **Añadir**: acepta una URL, `owner/repo` o texto libre y devuelve el registro existente si lo hay. Las fuentes se deduplican por clave canónica (`repo:owner/name`, `url:` canónica sin parámetros de seguimiento, o `idea:<hash>`).
- Filtros guardados, reutilizables por nombre desde la lista y por los agentes.
- **Puntuación**: cada hallazgo abierto recibe una nota de 0 a 100 con sus motivos (coincide con una carencia abierta, reaparece, estrellas, licencia permisiva, reciente, repositorio concreto). Los hallazgos ya decididos puntúan 0.
- **¿Ya lo cubre alguna app?**: compara las palabras del hallazgo (con alias español-inglés) con el árbol de capacidades y responde *ya cubierto*, *cubierto en parte* o *nada*.
- Conversación por hallazgo con notas, y **Proponer apps (IA)**: el modelo local sugiere una app para cada hallazgo sin propuesta (sin sobrescribir nunca una decisión de una persona).
- **Propuestas**: todas las propuestas en una lista, filtrable por estado, app, origen y palabras, con cambio de estado desde la fila.
- **Novedades**: hallazgos nuevos, cambios de estado y entregas desde la última visita, el último día, semana o mes.

**Preguntas e investigación**
- **Pregunta a Darwin**: una pregunta en lenguaje natural que responde el modelo local de la familia a partir del árbol, los hallazgos y las carencias, citando hallazgos por número y nombrando las apps que lo cubren.
- **Investigaciones**: un radar por carencias ordena las carencias abiertas según cuánto ayudaría una búsqueda y genera consultas de GitHub y web para cada una. Puede ejecutar la búsqueda en GitHub (y una búsqueda web sin clave) y registrar los resultados.
- **Preguntas guardadas**: preguntas del tipo «avísame cuando…» que se repiten cada cuatro horas; las comprobaciones posteriores listan solo hallazgos, cambios de estado y apps nuevos, y envían una notificación a la familia.

**Árbol de capacidades y carencias**
- **Árbol**: Faustus > Hoard Hub > Hoards > módulos absorbidos > capacidades > las herramientas que Faustus ve de verdad, con evidencia (*declarada* desde un manifiesto, *viva* desde el catálogo de herramientas de Faustus) y estado. La búsqueda «¿Quién hace…?» responde qué apps ya cubren algo; las descripciones que niegan una función nunca cuentan como coincidencia.
- **Carencias**: cosas que se quieren y que ninguna app hace aún, con la condición que las haría posibles. Los Hoards cuyo `OBJETIVOS.md` es una lista simple la alimentan al importar; los registros largos se leen con una heurística de señales más el modelo local, que se queda solo con lo que falta por hacer. Las importaciones son idempotentes y cierran las carencias cuya línea desaparece.
- **Conciliación de carencias**: las carencias que el árbol ya responde se muestran aparte como *posiblemente obsoletas* con su evidencia y no cuentan como abiertas. Nada se cierra solo: una persona confirma o descarta cada una.

**Trajes**
Un traje es una configuración de trabajo reutilizable para un tipo de encargo: objetivo, entradas, conceptos del dominio, operaciones, vistas, criterios de aceptación, receta y puntos que requieren el criterio de un modelo. Cada operación apunta a un nodo del árbol (`capability_key`); una operación sin clave es una capacidad que aún no existe y dice por qué. El estado se calcula en cada lectura:

| Estado | Significado |
|---|---|
| `proposed` | ninguna operación requerida está respaldada |
| `partial` | algunas operaciones requeridas están respaldadas |
| `backed` | todas las operaciones requeridas apuntan a un nodo existente marcado como implementado con evidencia |
| `evaluated` | se importó una evaluación exportada por Pygmalion's Hoard (`pygmalion-suit-eval/1`); el estado de respaldo de ese momento se guarda al lado |

Un nodo cuenta como respaldado solo tras `darwin_capability_mark` con al menos un enlace de evidencia (un `commit`, un `test` como `fichero::nombre`, o una ruta `qa_file`). Marcar sin evidencia se rechaza, desmarcar quita la prueba, y ambas cosas quedan en el historial. Se siembra una vez un conjunto inicial de seis trajes.

**Entregas**
- **Comprobar entregas** (solo git local, sin fetch) prueba cada entrega, de la prueba más fuerte a la más débil, y anota cuál se usó: el commit declarado está en main (`direct`), está en otro repositorio local (`other_repository`), lo nombra un trailer de cherry-pick, tiene un equivalente en main (mismo `git patch-id`, o mismo asunto y fecha de autor), o el commit declarado ya no existe y la tarea de Ágora de la entrega nombra lo que llegó a main. El código que llegó con una app integrada en otro repositorio se marca `imported`. En otro caso el resultado es `not_in_main` o `unknown` con el motivo.
- **Mapa de repositorios**: asocia repositorios renombrados, la antigua carpeta paraguas, espacios de trabajo de Ágora y apps integradas en otra como subcarpeta. Tus propios alias (nombre antiguo → repositorio, subcarpeta o buscar en todos) prevalecen sobre los integrados.
- Una entrega se puede corregir (repositorio, commit, tarea de Ágora); la declaración anterior se conserva y la entrega se vuelve a comprobar al instante.

**Captura y lectura**
- **Bandeja**: las capturas sin fuente todavía (una nota de chat, una captura de pantalla) nunca se descartan. **Leer capturas (OCR)** lee las capturas con el OCR de la familia, enlaza las URL que encuentra y los nombres `owner/repo` que GitHub confirma; también se ejecuta tras una sincronización de chat.
- **Cuentas para leer posts**: conecta X, Instagram, Threads, TikTok, Reddit, Facebook o YouTube; Links abre una ventana de inicio de sesión en este ordenador y la persona inicia sesión (ninguna contraseña pasa por Darwin). **Leer posts** lee los posts que hay detrás de los hallazgos y los convierte en capturas con título legible y resumen.
- El triaje con el modelo local marca el ruido y propone estados.

**En Faustus**
- Una tarjeta de Darwin en el resumen de cada proyecto de Faustus: hallazgos abiertos que merecen una mirada, propuestas por estado, carencias y últimos cambios del Hoard del que trata el proyecto (toda la familia y las próximas búsquedas del radar en los proyectos de Research y ecosistema). Se sirve en `GET /api/hoard/darwin/panel` a través del hub; la página muestra lo mismo con `?embed=panel&space=…&project=…`.
- **Brain de Faustus**: Darwin escribe notas Markdown enlazadas en `Notes/Darwin/` (un índice, una nota por app con lo propuesto, entregado y pendiente, una nota por hallazgo vivo) cada pocas horas y con `darwin_brain_export`. Solo se reescriben o borran las notas marcadas `generated_by: darwins-hoard`.
- **Resumen**: recuentos, hallazgos por estado, apps con más propuestas, orígenes, entregas (declaradas y probadas en main), estado de la sincronización del chat e importaciones con el hash de cada fichero.

## De dónde vienen los datos

| Origen | Cómo |
|---|---|
| Ficheros del radar | `RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md` (carpeta configurada en ajustes) y las entradas exportadas a `radar-ideas.md`. Idempotente; una línea editada pasa a ser una segunda aparición. |
| Ágora | Las tareas de cada espacio que citan `radar #N` o llevan una etiqueta `darwin:<id>` se convierten en propuestas para la app del espacio; una tarea hecha con commits añade una entrega declarada. |
| WhatsApp «Gittrend» | Solo lectura, a través del puente de WhatsApp de Faustus, página a página con cursor; no se envía ni se marca nada como leído. La cobertura es lo que conserva el puente (60 días). Si el puente está parado, la sincronización lo arranca a través de Faustus y vuelve a leer. Si el Hub ha movido Faustus a una Spark, las llamadas lo siguen. Las capturas van a la bandeja y al OCR. |
| Links' Hoard | Cada pocas horas y con `darwin_import_links`: los enlaces con la etiqueta `darwin` y todos los repositorios de GitHub guardados allí. |
| Otras apps y agentes | `darwin_ingest` y `darwin_add`. |
| Árbol de capacidades | `/api/apps` del hub, `/api/tools/catalog` de Faustus y los manifiestos `faustus-plugin.json` cuando el hub no está. |

## Cómo arrancarlo

```
Iniciar Darwin's Hoard.cmd
```

o arráncalo desde el Hoard Hub, o ejecuta `python -m darwin_hoard`. Requiere Python 3.11+ y FastAPI; Hoard Link va incluido en `darwin_hoard/hoard_link`. Los datos están en `data/darwin.db` (SQLite); los ajustes en `data/settings.json` (carpeta del radar, URL de Faustus, chat de WhatsApp e intervalo de sincronización, intervalo de refresco del árbol).

## Conexión con Faustus y el Hub

El manifiesto del plugin es `faustus-plugin.json`. El puente MCP (`mcp_server.py`, stdio) reenvía cada llamada a la app en marcha con el token de `data/mcp-token`. Nunca arranca la app: mientras Darwin está parado lista las herramientas desde el catálogo del paquete y una llamada responde `not_running`.

Herramientas MCP, por grupos:
- Hallazgos: `darwin_overview`, `darwin_find`, `darwin_source`, `darwin_add`, `darwin_ingest`, `darwin_propose`, `darwin_set_state`, `darwin_changes_since`, `darwin_inbox`, `darwin_triage`, `darwin_discuss`, `darwin_proposals`, `darwin_saved_filters`, `darwin_ask`, `darwin_coverage`.
- Árbol y carencias: `darwin_tree`, `darwin_capability_find`, `darwin_tree_refresh`, `darwin_capability_mark`, `darwin_gaps`, `darwin_gap_add`, `darwin_gaps_reconcile`, `darwin_gaps_import`.
- Entregas: `darwin_verify_deliveries`, `darwin_delivery_fix`, `darwin_repo_aliases`, `darwin_repo_alias_set`.
- Trajes: `darwin_suits`, `darwin_suit_get`, `darwin_suit_save`, `darwin_suit_delete`, `darwin_suits_seed`, `darwin_suit_import_eval`.
- Investigación: `darwin_radar_plan`, `darwin_radar_run`, `darwin_watch_add`, `darwin_watches`, `darwin_watches_check`, `darwin_watch_update`.
- Captura y lectura: `darwin_whatsapp_chats`, `darwin_sync_whatsapp`, `darwin_read_screenshots`, `darwin_accounts`, `darwin_account_login`, `darwin_read_posts`, `darwin_import_links`, `darwin_import_legacy`.
- Faustus: `darwin_brain_export`, `darwin_panel`.

La API REST los refleja bajo `/api/` (`/api/coverage`, `/api/radar/plan`, `/api/radar/run`, `/api/watches`, `/api/proposals`, `/api/filters`, `/api/panel`, `/api/suits`, `/api/evaluations`, `/api/capabilities/mark`, `/api/gaps`, `/api/deliveries/{id}/fix`). Desde PowerShell, los agentes programados llaman a `darwin.ps1 <herramienta> -ArgsFile args.json` (JSON UTF-8) y `darwin.ps1 -List`. Las instrucciones del radar están en [docs/RADAR.md](docs/RADAR.md).

**Skills.** La app lleva procedimientos de la biblioteca de skills de la familia para los agentes que se conectan (`discovery-to-capability`, `learn-this-repo`, `codebase-onboarding`, `search-first`, `reuse-before-you-write`, `deep-research`), que se leen con `skills_list` y `skill_read` y se asignan en la página de skills (`/api/agent/skills/page`) o en la pestaña Skills del hub.

**App Dock.** Junto a un chat de Faustus, la página registra `darwin_open`, `darwin_filter` y `darwin_view` mediante `window.HoardApp`: resuelven registros por id o nombre único (los nombres ambiguos devuelven candidatos), aplican filtros y cambian de sección, y informan de la sección, la selección y los filtros actuales. `dock/changed` refresca las vistas montadas sin perder lo que haya escrito en los formularios.

## Estructura del proyecto

| Ruta | Contenido |
|---|---|
| `darwin_hoard/` | la app (backend FastAPI, página, `hoard_link` incluido) |
| `darwin_ingest/` | ingesta de ficheros del radar y otras fuentes |
| `mcp_server.py` | puente MCP por stdio |
| `darwin.ps1` | llamador de herramientas desde PowerShell |
| `faustus-plugin.json` | manifiesto del plugin |
| `docs/` | `INGESTION.md`, `RADAR.md`, `ICONS.md`, `SKILL-IMPACTS.md` |
| `tests/` | batería de pruebas |
| `data/` | base de datos, ajustes, token (no versionado) |

## Pruebas

```
.venv\Scripts\python.exe -m pytest
```

Las pruebas usan solo carpetas de datos temporales y fixtures; no tocan ningún chat, hub ni repositorio real.

## Licencia

MIT. Véase `LICENSE`.
