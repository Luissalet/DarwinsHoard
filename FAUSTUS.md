# Darwin's Hoard — for Faustus and agents

**Purpose:** before proposing, researching or building something, ask Darwin whether it was already seen, proposed, delivered or covered by another app.

## When to call what

| Need | Tool |
|---|---|
| "Have we seen this repo/URL?" | `darwin_add` (returns the existing record, never duplicates) or `darwin_find` |
| Full story of a discovery | `darwin_source` (genealogy: appearances, proposals, deliveries, proof in main) |
| "Which app already does X?" | `darwin_capability_find` (answers with the tree path) |
| Browse the family | `darwin_tree` (subtree from a node key, e.g. `hoardhub`, `app:writer`) |
| Propose an idea for an app | `darwin_propose` |
| Mark state | `darwin_set_state` (`integrada` requires a commit or an Ágora task) |
| What changed recently | `darwin_changes_since`, `darwin_overview` |
| Things nobody does yet | `darwin_gaps`, `darwin_gap_add` |
| Notes with no link yet | `darwin_inbox` |
| Bulk ingestion from another app | `darwin_ingest` |
| Refresh evidence | `darwin_verify_deliveries` (git ancestry, no fetch; `via` says the proof: direct, other_repository, cherry_pick_trailer, patch_id, subject_date, agora_*; `imported` for apps folded in without history), `darwin_tree_refresh` |
| Where an old repository name lives today | `darwin_repo_aliases` (built-in + Luis's aliases, folded apps' subfolders, names nothing resolves), `darwin_repo_alias_set` |
| WhatsApp «Gittrend» | `darwin_whatsapp_chats`, `darwin_sync_whatsapp` (read only, incremental by cursor) |
| A question in plain words | `darwin_ask` (local retrieval + the family's local model; cites discoveries `[#id]`) |
| Suggest apps for unproposed discoveries | `darwin_triage` (pending proposals with origin agent) |
| Debate a proposal | `darwin_discuss` (one Ágora thread per proposal, space `darwin`) |
| What is most worth a look | `darwin_find` with `order: fitness` (score and reasons per discovery) |
| Links saved for Darwin | `darwin_import_links` (tag `darwin` in Links, or any GitHub repository) |
| Darwin in the Brain | `darwin_brain_export` (Notes/Darwin, linked notes; also every few hours) |
| Read the posts behind discoveries | `darwin_accounts`, `darwin_account_login` (Luis signs in himself in Links' window), `darwin_read_posts` |
| Screenshots with no link | `darwin_read_screenshots` (family OCR; URLs taken, `owner/repo` only when GitHub confirms it; each image read once) |
| Re-read the legacy radar files and Ágora | `darwin_import_legacy` (idempotent) |
| «¿Qué encargos sabes resolver?» (trajes) | `darwin_suits` (estado: proposed, partial, backed, evaluated), `darwin_suit_get` (operaciones con su prueba), `darwin_suit_save`, `darwin_suits_seed` |
| Marcar una capacidad como implementada | `darwin_capability_mark` (exige prueba: commit, test o fichero de QA; sin ella se rechaza) |
| Carencias que ya podrían estar resueltas | `darwin_gaps_reconcile` (marca «posiblemente obsoleta» con la prueba; confirmar/descartar lo decide una persona) |
| Resultados de evaluar un traje en Pygmalion | `darwin_suit_import_eval` (JSON `pygmalion-suit-eval/1` o ruta del fichero) |
| "Does an app already do this?" for a discovery or a text | `darwin_coverage` (covered / partial / gap with the matching apps and nodes; explains, never blocks) |
| What the radar should look for next | `darwin_radar_plan` (gaps ranked, GitHub and web queries, candidates already held; `notify: false` = nothing new, stay quiet) |
| Search GitHub for the top gaps | `darwin_radar_run` (`add: true` registers the new repositories; link collections are left out) |
| «Avísame cuando…» | `darwin_watch_add`, `darwin_watches`, `darwin_watches_check` (notify only with news), `darwin_watch_update` |
| Proposals across the family | `darwin_proposals` (state, app, origin, words) |
| Named history filters | `darwin_saved_filters`, then `darwin_find` with `saved` |
| What Darwin knows about one Hoard (or the family) | `darwin_panel` (`app`, `space` or `project`; what Faustus's project overview shows) |

## Rules

- Never fold states: proposal, implementation, verification and operation are separate axes.
- A declared delivery is not proof; `evidence.commit_ancestry = integrated` is code proof, not a functional test. With `via` other than `direct` the proof is an equivalent commit (`equivalent_of` = the declared one) or what the Ágora task says reached main; `imported` means the declared commit cannot be checked locally.
- Un nombre de capacidad en el árbol no prueba que funcione: un traje solo está «backed» si cada operación necesaria existe y tiene prueba registrada.
- Una carencia marcada «posiblemente obsoleta» sigue abierta hasta que alguien la confirme; no la cierres por tu cuenta sin comprobarla.
- WhatsApp access is read only through Faustus's bridge; nothing is sent or marked as read.

## What it cannot do (yet)

- Run a schedule by itself: the gap-driven radar and the saved questions are tools (`darwin_radar_plan`, `darwin_radar_run`, `darwin_watches_check`) that a scheduled task calls; Darwin checks the saved questions on its own every four hours, but the daily radar task's instructions ([docs/RADAR.md](docs/RADAR.md)) are applied to that task by Luis.
- Read WhatsApp history the bridge never received.

## Icono de familia (2026-11-02)

Dragon verde y arbol evolutivo dorado preparados para el Hub (PNG512) y Windows (ICO de seis tamanos). Cabecera, favicon y PWA conservan el icono anterior hasta sustituir los dos PNG static, reservados por la tarea1866. Referencia en docs/ICONS.md.
