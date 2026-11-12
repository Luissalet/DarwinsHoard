# Darwin's Hoard

A local app that keeps every discovery that could improve Faustus or one of the Hoards (a GitHub repository, an article, a paper, a reel, a loose idea) together with its source, the proposals made for each app, what was delivered, and the capability tree of the whole family.

[Leer en español](README.es.md)

## What it is

Before anyone spends time on a link, Darwin answers two questions: *have we seen this already, and what happened to it?* and *which app already does this?* A discovery is traced from its capture to its evidence:

capture → source → idea → proposal (idea × app) → delivery (proposal × repository/commit/task) → evidence.

State axes are kept apart and never folded into one flag:

- proposal: `pendiente`, `investigando`, `debatida`, `aceptada`, `aplazada`, `descartada`, `cubierta`;
- implementation per delivery: `sin_implementar`, `parcial`, `integrada`, `sustituida`;
- verification per delivery: `documentada`, `probada`, `recomprobar`, `desconocida`;
- operation per tree node: `disponible`, `detenida`, `desconocida`.

What a document or a person declared is stored as declared; checks add evidence next to it without overwriting it. Every state change keeps the previous value in a history.

Part of the Hoard family (Faustus copilot, Hoard Hub window, MCP bridge). Port **5233**, id `darwin`.

## What it does

**Discoveries**
- **Historial**: every discovery, filterable by text, `owner/repo`, URL or radar number, state, app, origin and pinned ones, in several orders. Each opens its genealogy: appearances with file and line, proposals per app with their history, deliveries with commits and whether each commit is in the main branch.
- **Añadir** box: takes a URL, `owner/repo` or free text and returns the existing record when there is one. Sources are deduplicated by canonical key (`repo:owner/name`, canonical `url:` without tracking parameters, or `idea:<hash>`).
- Saved filters, reusable by name from the list and by agents.
- **Puntuación**: every open discovery gets a 0-100 score with its reasons (matches an open gap, keeps coming back, stars, permissive licence, recent, concrete repository). Decided discoveries score 0.
- **¿Ya lo cubre alguna app?**: compares a discovery's words (with Spanish-English aliases) against the capability tree and answers *ya cubierto*, *cubierto en parte* or *nada*.
- Discussion thread per discovery with notes, and **Proponer apps (IA)**, where the local model suggests an app for each discovery without a proposal (never overwriting a person's decision).
- **Propuestas**: every proposal in one list, filterable by state, app, origin and words, with state changes from the row.
- **Novedades**: new discoveries, state changes and deliveries since the last visit, day, week or month.

**Questions and research**
- **Pregunta a Darwin**: a question in plain words answered by the family's local model from the tree, the discoveries and the gaps, citing discoveries by number and naming the apps that cover it.
- **Investigaciones**: a radar by gaps ranks open gaps by how much a search would help and builds GitHub and web queries for each. It can run the GitHub search (and a keyless web search) and register the results.
- **Preguntas guardadas**: «avísame cuando…» questions re-asked every four hours; later checks list only new discoveries, state changes and apps, and send a family notification.

**Capability tree and gaps**
- **Árbol**: Faustus > Hoard Hub > Hoards > absorbed modules > capabilities > the tools Faustus actually sees, with evidence (*declarada* from a manifest, *viva* from Faustus's tool catalogue) and state. The «¿Quién hace…?» search answers which apps already cover something; descriptions that deny a feature never count as a match.
- **Carencias**: things wanted that no app does yet, with the condition that would make them possible. Hoards whose `OBJETIVOS.md` is a plain list feed it on import; long logs are read with a cue heuristic plus the local model, which keeps only what is still to do. Imports are idempotent and close gaps whose line disappears.
- **Gap reconciliation**: gaps the tree now answers are shown apart as *possibly stale* with the evidence and are not counted as open. Nothing is closed automatically; a person confirms or dismisses each one.

**Suits (Trajes)**
A suit is a reusable work configuration for a kind of engagement: objective, inputs, domain concepts, operations, views, acceptance criteria, recipe and points needing a model's judgement. Each operation points to a tree node (`capability_key`); an operation with no key is a capability that does not exist yet and says why. Status is computed on every read:

| Status | Meaning |
|---|---|
| `proposed` | none of the required operations is backed |
| `partial` | some required operations are backed |
| `backed` | every required operation points to an existing node marked implemented with evidence |
| `evaluated` | an evaluation exported by Pygmalion's Hoard (`pygmalion-suit-eval/1`) was imported; the backing state at that moment is stored next to it |

A node counts as backed only after `darwin_capability_mark` with at least one evidence link (a `commit`, a `test` as `file::name`, or a `qa_file` path). Marking without evidence is refused, unmarking removes the proof, and both are kept in the history. A starter set of six suits is seeded once.

**Deliveries**
- **Comprobar entregas** (local git only, no fetch) proves each delivery, strongest first, and records which proof was used: the declared commit is in main (`direct`), is in another local repository (`other_repository`), is named by a cherry-pick trailer, has an equivalent in main (same `git patch-id`, else same subject and author date), or the declared commit is gone and the delivery's Ágora task names what reached main. Code that arrived with an app folded into another repository is marked `imported`. Otherwise the result is `not_in_main` or `unknown` with the reason.
- **Mapa de repositorios**: maps renamed repositories, the old umbrella folder, Ágora workspaces and apps folded into another as a subfolder. Your own aliases (old name → repository, subfolder, or search all) win over the built-in ones.
- A delivery can be corrected (repository, commit, Ágora task); the old declaration is kept and the delivery is rechecked at once.

**Capture and reading**
- **Bandeja**: captures with no source yet (a chat note, a screenshot) are never dropped. **Leer capturas (OCR)** reads screenshots with the family's OCR, links the URLs it finds and the `owner/repo` names GitHub confirms; it also runs after a chat sync.
- **Cuentas para leer posts**: connect X, Instagram, Threads, TikTok, Reddit, Facebook or YouTube; Links opens a sign-in window on this computer and the person signs in (no password passes through Darwin). **Leer posts** reads the posts behind discoveries and turns them into captures with a readable title and summary.
- Triage with the local model marks noise and proposes states.

**In Faustus**
- A Darwin card in each Faustus project's overview: open discoveries worth a look, proposals per state, gaps and latest changes for the Hoard the project is about (the whole family plus the radar's next searches for Research and ecosystem projects). Served at `GET /api/hoard/darwin/panel` through the hub; the page shows the same with `?embed=panel&space=…&project=…`.
- **Brain de Faustus**: Darwin writes linked Markdown notes under `Notes/Darwin/` (an index, one note per app with what was proposed, delivered and missing, one note per live discovery) every few hours and on `darwin_brain_export`. Only notes marked `generated_by: darwins-hoard` are rewritten or removed.
- **Resumen**: counts, discoveries per state, apps with most proposals, origins, deliveries (declared and proven in main), chat sync status and imports with the file hash of each.

## Where the data comes from

| Origin | How |
|---|---|
| Radar files | `RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md` (folder set in settings) and the entries exported to `radar-ideas.md`. Idempotent; an edited line becomes a second appearance. |
| Ágora | Tasks of every space that cite `radar #N` or carry a `darwin:<id>` label become proposals for the space's app; a done task with commits adds a declared delivery. |
| WhatsApp «Gittrend» | Read only, through Faustus's WhatsApp bridge, page by page with a cursor; nothing is sent or marked as read. Coverage is what the bridge keeps (60 days). If the bridge is stopped, the sync starts it through Faustus and reads again. When the Hub has moved Faustus to a Spark, the calls follow it. Screenshots go to the inbox and the OCR. |
| Links' Hoard | Every few hours and on `darwin_import_links`: links tagged `darwin` and every GitHub repository saved there. |
| Other apps and agents | `darwin_ingest` and `darwin_add`. |
| Capability tree | The hub's `/api/apps`, Faustus's `/api/tools/catalog`, and the `faustus-plugin.json` manifests when the hub is down. |

## Running

```
Iniciar Darwin's Hoard.cmd
```

or start it from the Hoard Hub, or run `python -m darwin_hoard`. Requires Python 3.11+ and FastAPI; Hoard Link is vendored in `darwin_hoard/hoard_link`. Data lives in `data/darwin.db` (SQLite); settings in `data/settings.json` (radar folder, Faustus URL, WhatsApp chat and sync interval, tree refresh interval).

## Connection with Faustus and the Hub

The plugin manifest is `faustus-plugin.json`. The MCP bridge (`mcp_server.py`, stdio) proxies every call to the running app with the token in `data/mcp-token`. It never starts the app: while Darwin is stopped it lists the tools from the package's catalogue and a call answers `not_running`.

MCP tools, by group:
- Discoveries: `darwin_overview`, `darwin_find`, `darwin_source`, `darwin_add`, `darwin_ingest`, `darwin_propose`, `darwin_set_state`, `darwin_changes_since`, `darwin_inbox`, `darwin_triage`, `darwin_discuss`, `darwin_proposals`, `darwin_saved_filters`, `darwin_ask`, `darwin_coverage`.
- Tree and gaps: `darwin_tree`, `darwin_capability_find`, `darwin_tree_refresh`, `darwin_capability_mark`, `darwin_gaps`, `darwin_gap_add`, `darwin_gaps_reconcile`, `darwin_gaps_import`.
- Deliveries: `darwin_verify_deliveries`, `darwin_delivery_fix`, `darwin_repo_aliases`, `darwin_repo_alias_set`.
- Suits: `darwin_suits`, `darwin_suit_get`, `darwin_suit_save`, `darwin_suit_delete`, `darwin_suits_seed`, `darwin_suit_import_eval`.
- Research: `darwin_radar_plan`, `darwin_radar_run`, `darwin_watch_add`, `darwin_watches`, `darwin_watches_check`, `darwin_watch_update`.
- Capture and reading: `darwin_whatsapp_chats`, `darwin_sync_whatsapp`, `darwin_read_screenshots`, `darwin_accounts`, `darwin_account_login`, `darwin_read_posts`, `darwin_import_links`, `darwin_import_legacy`.
- Faustus: `darwin_brain_export`, `darwin_panel`.

The REST API mirrors these under `/api/` (`/api/coverage`, `/api/radar/plan`, `/api/radar/run`, `/api/watches`, `/api/proposals`, `/api/filters`, `/api/panel`, `/api/suits`, `/api/evaluations`, `/api/capabilities/mark`, `/api/gaps`, `/api/deliveries/{id}/fix`). From PowerShell, scheduled agents call `darwin.ps1 <tool> -ArgsFile args.json` (UTF-8 JSON) and `darwin.ps1 -List`. Radar instructions are in [docs/RADAR.md](docs/RADAR.md).

**Skills.** The app carries procedures from the family's skill library for connecting agents (`discovery-to-capability`, `learn-this-repo`, `codebase-onboarding`, `search-first`, `reuse-before-you-write`, `deep-research`), readable with `skills_list` and `skill_read`, assignable on the skills page (`/api/agent/skills/page`) or in the hub's Skills tab.

**App Dock.** Beside a Faustus chat, the page registers `darwin_open`, `darwin_filter` and `darwin_view` through `window.HoardApp`: they resolve records by id or unique name (ambiguous names return candidates), apply filters and switch sections, and report the current section, selection and filters. `dock/changed` refreshes the mounted views without losing pending form input.

## Project layout

| Path | Contents |
|---|---|
| `darwin_hoard/` | the app (FastAPI backend, page, vendored `hoard_link`) |
| `darwin_ingest/` | ingestion of radar files and other sources |
| `mcp_server.py` | stdio MCP bridge |
| `darwin.ps1` | PowerShell caller for tools |
| `faustus-plugin.json` | plugin manifest |
| `docs/` | `INGESTION.md`, `RADAR.md`, `ICONS.md`, `SKILL-IMPACTS.md` |
| `tests/` | test suite |
| `data/` | database, settings, token (not tracked) |

## Tests

```
.venv\Scripts\python.exe -m pytest
```

Tests use temporary data folders and fixtures only; no real chat, hub or repository is touched.

## Licence

MIT. See `LICENSE`.
