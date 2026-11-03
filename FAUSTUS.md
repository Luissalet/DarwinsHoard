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
| Refresh evidence | `darwin_verify_deliveries` (git ancestry, no fetch), `darwin_tree_refresh` |
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

## Rules

- Never fold states: proposal, implementation, verification and operation are separate axes.
- A declared delivery is not proof; `evidence.commit_ancestry = integrated` is code proof, not a functional test.
- Un nombre de capacidad en el árbol no prueba que funcione: un traje solo está «backed» si cada operación necesaria existe y tiene prueba registrada.
- Una carencia marcada «posiblemente obsoleta» sigue abierta hasta que alguien la confirme; no la cierres por tu cuenta sin comprobarla.
- WhatsApp access is read only through Faustus's bridge; nothing is sent or marked as read.

## What it cannot do (yet)

- The radar through Darwin is written ([docs/RADAR.md](docs/RADAR.md)) but the scheduled task still has to be switched to it.
- Read WhatsApp history the bridge never received.

## Icono de familia (2026-11-02)

Dragon verde y arbol evolutivo dorado preparados para el Hub (PNG512) y Windows (ICO de seis tamanos). Cabecera, favicon y PWA conservan el icono anterior hasta sustituir los dos PNG static, reservados por la tarea1866. Referencia en docs/ICONS.md.
