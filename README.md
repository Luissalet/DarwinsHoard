# Darwin's Hoard

Keeps every discovery that could improve Faustus or one of the Hoards (a GitHub repository, an article, a paper, a reel, a loose idea) together with where it came from, what was proposed for which app, what was delivered, and the capability tree of the whole family. It answers two questions before anyone spends time on a link: *have we seen this already, and what happened to it?* and *which app already does this?*

Port **5233**, id `darwin`, part of the Hoard family (Faustus copilot, Hoard Hub window, MCP bridge).

## What it shows

| View | What is in it |
|---|---|
| **Resumen** | **Pregunta a Darwin**: a question in plain words («¿qué tenemos para transcribir reuniones?») answered from the tree, the discoveries and the gaps by the family's local model, citing discoveries by number and naming the apps that cover it. Counts, discoveries per state, apps with most proposals, where discoveries come from, deliveries (declared and proven in the main branch), the Gittrend chat sync and the imports with the file hash of each. |
| **Historial** | Every discovery, filterable by text, `owner/repo`, URL or radar number, state, app, origin and "only the ones I marked 📌", in several orders. Each one opens its genealogy: appearances with file and line, proposals per app with their history, deliveries with commits and whether the commit is in the main branch. The aggregate state counts per proposal (an app, or one capability of an app), not per app: with two capabilities proposed for one app and only one integrated, the discovery is *mixta*, not *integrada*. Proposal states can be changed and new proposals made from there. **Debatir en el Ágora** opens one thread per proposal in the Ágora (space `darwin`) with the genealogy, shows its messages in the card and takes notes (posted by the agent `darwin`, marked as Luis's). **Proponer apps (IA)** has the local model suggest an app for every discovery without a proposal (pending proposals with origin *agent*; Luis's decisions are never overwritten; noise is marked as such). |
| **Historial** (saved filters, coverage) | **Guardar filtro** keeps the current search, state, app, origin, order and 📌 under a name that the list, `darwin_find` (`saved: "<name>"`) and other agents can reuse; **Borrar filtro** removes it. In a discovery's card, **¿Ya lo cubre alguna app?** compares its words (with the Spanish-English aliases) with the capability tree: *ya cubierto* (half of its ideas, three or more, in one app with live, tested or backed nodes), *cubierto en parte* or *nadie lo hace*, with the matching apps and nodes. It explains; it never blocks. `?open=<id>` in the address opens a discovery and `?app=<id>` scopes the lists to one app. |
| **Propuestas** | Every proposal (a discovery for an app) in one list, filterable by state, app, origin (Luis, agent, Ágora, radar…) and words, with counts per state; the state is changed from the row and a row opens its discovery. |
| **Investigaciones** | **Radar por carencias**: the open gaps ranked by how much a search would help (never searched, open for long, it names an app go up; candidates already in Darwin or a tree that may already cover it go down), each with its GitHub and web queries (English keywords written once by the family's local model and cached per gap; the tree's aliases without a model), the discoveries that may already answer it and whether the tree may cover it. **Buscar en GitHub** runs the first three (or one with **Buscar esta**) through GitHub's anonymous search, leaves out link collections, says which repositories Darwin already knew and, with **Guardar los repos nuevos**, registers the new ones (channel radar, linked to the gap). **Preguntas guardadas**: «avísame cuando…» questions asked again every four hours with the local retrieval of `darwin_ask`; the first check is the baseline, later ones list only new discoveries, state changes and apps, and send a family notification. Pause, resume, mark as read or delete each one. A scheduled task calls `darwin_radar_plan` / `darwin_watches_check` and stays quiet when `notify` is false. |
| **Panel in Faustus** | Each Faustus project's overview shows a Darwin card for the Hoard the project is about (resolved from its Ágora space or name; Research and ecosystem show the whole family plus the radar's next searches): open discoveries worth a look, proposals per state, gaps and the latest changes, with links into Darwin. Faustus reads it through the hub (`GET /api/hoard/darwin/panel`); Darwin's own page shows the same with `?embed=panel&space=…&project=…`. |
| **Bandeja** | Captures that have no source yet (a chat note, a screenshot without a link), with the image and the text the OCR read in it. They are never dropped; one click turns them into a discovery. **Leer capturas (OCR)** reads the unread screenshots with the family's OCR (Kafka's engine) and links the URLs it finds and the `owner/repo` names GitHub confirms; it also runs on its own after a chat sync brings new messages. |
| **Árbol** | Faustus (root) > Hoard Hub > Hoards > absorbed modules > capabilities > the tools Faustus really sees, with evidence (*declarada* from a manifest, *viva* from Faustus's tool catalogue) and state (*disponible*, *detenida*). A "¿Quién hace…?" search answers which apps already cover something, with the path of each match; what a description denies («Does not perform OCR…») never counts as a match. |
| **Cuentas para leer posts** (in Resumen) | Connect X, Instagram, Threads, TikTok, Reddit, Facebook or YouTube: Links opens a sign-in window on this computer and Luis signs in himself (no password ever passes through Darwin); the session lives in Links and also serves its downloads. **Leer posts** reads the posts behind discoveries (`x.com/…/status/…`, Instagram posts and reels…) through Links' `read_post`: the text becomes a capture of the post, the post gets a readable title and summary, and the repositories and links in it become discoveries (bare `owner/repo` only when GitHub confirms it). A post the site refuses stops the run and says which account to connect; nothing is marked, so it is read once the account is connected. It also runs after a chat sync brings new messages. |
| **Puntuación** | Every open discovery gets a score (0-100) with its reasons: it matches an open gap, it keeps coming back, stars, a permissive licence, it is recent, it is a concrete repository. Historial sorts by it (**Más interesantes**) and each card says why. Decided discoveries (integrated, covered, discarded) score 0. |
| **Brain de Faustus** | Darwin writes itself into Faustus's Brain as linked Markdown notes under `Notes/Darwin/` (an index, one note per app with what was proposed, delivered and still missing, one note per live discovery with its genealogy and score), every few hours and with `darwin_brain_export`. The vault is the shared one when Faustus has no login, `admin`'s otherwise (`brain_owner`, `brain_vault_dir`). Only notes marked `generated_by: darwins-hoard` are rewritten or removed. |
| **Novedades** | New discoveries, state changes and deliveries since the last visit (or the last day, week or month). |
| **Carencias** | Things that are wanted and no app does yet, with the condition that would make them possible. The Hoards whose `OBJETIVOS.md` is a plain list feed it on every import (one gap per item, for that app); an item that leaves its file closes its gap. Long logs (Faustus's, Writer's) are skipped. |

| **Carencias** (reconciled) | Gaps the capability tree now answers are shown apart as *possibly stale*, with the evidence, and are not counted as open. Nothing is closed automatically: you confirm (state *resuelta*) or dismiss each one. |
| **Trajes** (suits) | The library of suits: reusable work configurations for a kind of engagement (objective, inputs and how each is identified, domain concepts, the operations used, views, acceptance criteria, recipe, points that need a model's judgement). A suit shows what engagements Darwin can solve and how far each is backed. See below. |

The **Añadir** box in the header takes a URL, `owner/repo` or free text and returns the existing record when there is one.

## Suits and backing

A suit is a reusable work configuration for a kind of job. Each operation of a suit points to a node of the capability tree (`capability_key`); an operation with no key is a capability that does not exist yet and says why. Status of a suit, computed every time it is read:

| Status | Meaning |
|---|---|
| `proposed` | none of the required operations is backed |
| `partial` | some required operations are backed; others are missing from the tree or only declared |
| `backed` | every required operation points to a node that exists in the tree **and** is marked implemented with evidence |
| `evaluated` | an evaluation exported by Pygmalion's Hoard (`pygmalion-suit-eval/1`) was imported; the backing state at that moment is stored next to it, so *evaluated* never hides what was missing |

A capability name proves nothing. A node counts as backed only after `darwin_capability_mark` with at least one evidence link: a `commit` (hash or `repo@hash`), a `test` (`file::name`) or a `qa_file` (path). Marking without evidence is refused; unmarking removes the proof and both are kept in the history. The proof lives apart from the tree, so a tree refresh does not lose it.

Six suits from research proposal 36 are seeded once (repository intake, small migration, web 3D product model, part budget, contradictory documentation, data to product), pointing at nodes that plausibly cover each step and naming the missing ones. None starts backed.

**Gap reconciliation.** A gap whose capability (explicit key, or the words of a backed capability or tool name found in its title and detail, for the same app) is backed with evidence is flagged *possibly stale* with that evidence. It stays `abierta` but is left out of the open count, the discovery score and the Brain notes. `darwin_gaps_reconcile` recomputes the flags (also after every mark and every tree refresh) and takes `confirm_ids` / `dismiss_ids` from a person. With `semantic: true` the local model also compares the open gaps with the backed capabilities of the whole tree (any app, by meaning, not by shared words) and flags the ones it finds answered *possibly stale* with reason `semantic`, the capability and its evidence; it never closes a gap, and a flag whose capability stops being backed disappears by itself.

**Gaps from objective logs.** The `OBJETIVOS.md` of Faustus and Writer are long logs, not lists. `darwin_gaps_import` (also run by `darwin_import_legacy`) reads them with a cue heuristic (open sections, "pendiente", "falta", unchecked boxes) and the local model, which keeps only what is still to do and writes it as a short title. Each gap carries its origin (file, section, line) and the import is idempotent: running it again adds nothing, moves a gap whose line moved, and closes the ones whose text left the file. At most 60 new gaps per run; `log_pending` says how many candidates are left for the next run.

**Fixing a delivery.** `darwin_delivery_fix` (`POST /api/deliveries/{id}/fix`) corrects the repository, the commit or the Ágora task of a delivery, keeps the old declaration in `declared.declared_before_fix`, writes a history row and checks the delivery again at once. `clear_commit` drops a commit that never existed; the ones that cannot be proven stay with their reason.

**Evaluation results.** `POST /api/evaluations` (or `darwin_suit_import_eval` with a JSON object or file path) takes the file Pygmalion's Hoard exports. It is refused unless it has at least one scored case; cases used to build an improvement arrive excluded and are listed.

## Data model

capture → source → idea → proposal (idea × app) → delivery (proposal × repository/commit/Ágora task) → evidence.

An Ágora task opened for a proposal carries it in its title, «… (Darwin 1013)» or «(Darwin 1016, 1046)». The Ágora import (`darwin_import_legacy`) links the task to each proposal it names and, once the task is `done` with commits, records every commit as a delivery of that proposal.

State axes are kept apart and never folded into one flag:

- proposal: `pendiente`, `investigando`, `debatida`, `aceptada`, `aplazada`, `descartada`, `cubierta`;
- implementation per delivery: `sin_implementar`, `parcial`, `integrada`, `sustituida`;
- verification per delivery: `documentada`, `probada`, `recomprobar`, `desconocida`;
- operation per tree node: `disponible`, `detenida`, `desconocida`.

What a document or a person declared is stored as declared; the commit check adds `evidence.commit_ancestry` (`integrated`, `imported`, `not_in_main`, or why it could not be checked) without overwriting it. A commit in the main branch is code evidence, not a functional test. Every state change keeps the previous value in `history`.

How **Comprobar entregas** (`darwin_verify_deliveries`, local git only, no fetch) proves a delivery, strongest first, with `via` saying which proof was used:

- `direct`: the declared commit is in main of the repository the delivery names. Old names go through the **Mapa de repositorios** (Resumen): renamed repositories (HoardLink → Hoard Hub, FieldDex → Hoard Dex…), the old `D:\LocalAI` umbrella (searched in every repository), Ágora space workspaces (Blood Arrows) and apps folded into another as a subfolder (Galton → Pygmalion `galton_hoard`, Funes/Argus/Disk Hoard → Talos, Midas → Coase, Borges → Writer's `publishing/borges`, Tantalus/Phileas → Hermes, Babel/Theseus → Vitruvius, Gulliver → Vulcan `studio_native/gulliver`, Laplace → Nightingale). Your own aliases (old name → repository, subfolder, or «buscar en todos») are saved in the setting `repo_aliases` and win over the built-in ones.
- `other_repository`: a multi-repository task declared under one name; the commit is in main of another local repository.
- `cherry_pick_trailer`: a main commit says «cherry picked from commit <id>» (works even when the original is gone).
- `patch_id` / `subject_date`: the commit exists (another branch, an unreachable object after a rewrite) and main holds an equivalent: same `git patch-id --stable`, else same subject and author date. `equivalent_of` keeps the declared commit, `commit` the one in main.
- `agora_resolution` / `agora_submission` / `agora_task`: the declared commit is gone (history rewritten, branch deleted) and the delivery's Ágora task names what reached main («Integrado en master (sha)», «Integrada en Prospero main sha», «old -> new» after a cherry-pick, the last submission's «Commits:» line, the task's commits), and that commit is in main. A tracker line without commit («✅ hecho (#527)») uses the tasks it cites; when it cites exactly one, that task is written into the delivery.
- `imported` (`history_not_imported`): the code arrived with an app folded into another repository without its history; the result names the folder, the commit that added it and the upstream commit recorded in `provenance/`. The declared commit cannot be checked locally, so the implementation state is left as declared.
- Otherwise `not_in_main` or `unknown` with `commit_not_found`, `no_commit_declared`, `invalid_commit_id` (the text is kept in `declared_commit`), `repository_not_mapped` or `repository_unavailable`. Several ids in one field («7cc2354 5e8241b») are checked one by one (`commits`).

A source is identified by `repo:owner/name` (lower case; the GitHub id, when known, joins renamed repositories), `url:<canonical URL>` (tracking parameters, `www.`, fragments and trailing slashes removed; posts on X, Instagram, TikTok, LinkedIn, Reddit and similar lose every query parameter, and twitter.com becomes x.com; older keys are merged on start and kept as aliases) or `idea:<hash>`.

## Where the data comes from

| Origin | How |
|---|---|
| Radar files | `RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md` (folder set in settings) and the 426-510 entries exported to `radar-ideas.md`. Idempotent: importing twice adds nothing; an edited line becomes a second appearance. |
| Ágora | Tasks of every space that cite `radar #N` (or carry a `darwin:<id>` label) become proposals for their space's app; a done task with commits adds a declared delivery in the repository the task names. |
| WhatsApp «Gittrend» | Read only, through Faustus's WhatsApp bridge (`/api/whatsapp/message-page`), page by page with a cursor; nothing is sent or marked as read, and a second sync repeats nothing. Coverage is what the bridge keeps (60 days), not the phone's whole history. If the bridge is stopped, the sync (and the chat list) starts it through Faustus (`POST /api/whatsapp/start`), waits until it is connected and reads again; the result then carries `bridge_started`. When the Hub has moved Faustus to a Spark («Run on»), WhatsApp, the capability tree and the Brain calls go to that Faustus (the Hub's `/api/placement`), since the session moves with it. Screenshots go to the inbox and through the OCR. |
| Links' Hoard | Every few hours (and `darwin_import_links`): the links saved in Links with the tag `darwin` and every GitHub repository saved there. Videos and other reading are left out. |
| Other apps and agents | `darwin_ingest` and `darwin_add`. |
| Capability tree | The hub's `/api/apps`, Faustus's `/api/tools/catalog`, and the `faustus-plugin.json` manifests when the hub is down. |

## Tools (MCP and the page)

`darwin_overview`, `darwin_find`, `darwin_source`, `darwin_add`, `darwin_propose`, `darwin_set_state`, `darwin_tree`, `darwin_capability_find`, `darwin_tree_refresh`, `darwin_gaps`, `darwin_gap_add`, `darwin_changes_since`, `darwin_inbox`, `darwin_ingest`, `darwin_verify_deliveries`, `darwin_repo_aliases`, `darwin_repo_alias_set`, `darwin_whatsapp_chats`, `darwin_sync_whatsapp`, `darwin_read_screenshots`, `darwin_ask`, `darwin_triage`, `darwin_discuss`, `darwin_accounts`, `darwin_account_login`, `darwin_read_posts`, `darwin_brain_export`, `darwin_import_links`, `darwin_import_legacy`, and for suits and gaps `darwin_suits`, `darwin_suit_get`, `darwin_suit_save`, `darwin_suit_delete`, `darwin_suits_seed`, `darwin_capability_mark`, `darwin_gaps_reconcile`, `darwin_gaps_import`, `darwin_delivery_fix`, `darwin_suit_import_eval`, and for the research views `darwin_coverage`, `darwin_radar_plan`, `darwin_radar_run`, `darwin_watch_add`, `darwin_watches`, `darwin_watches_check`, `darwin_watch_update`, `darwin_proposals`, `darwin_saved_filters`, `darwin_panel`.

REST for the research views: `GET /api/coverage?source_id=|text=`, `GET /api/radar/plan` (the page looks without moving the baseline), `POST /api/radar/run` (`web: true` also searches the keyless web, DuckDuckGo's HTML page as Faustus does, and reports or registers the pages), `GET|POST /api/watches`, `POST /api/watches/check`, `PATCH|DELETE /api/watches/{id}`, `GET /api/proposals`, `GET /api/filters`, `PUT|DELETE /api/filters/{name}`, `GET /api/panel?app=|space=|project=`.

REST for suits and gaps: `GET /api/suits[?status=]`, `GET|PUT|DELETE /api/suits/{slug}`, `POST /api/suits/seed`, `POST /api/suits/{slug}/evaluation`, `POST /api/evaluations`, `POST /api/capabilities/mark`, `GET /api/gaps`, `POST /api/gaps/reconcile`, `POST /api/gaps/import`, `POST /api/deliveries/{id}/fix`.

From PowerShell (scheduled agents, other apps): `darwin.ps1 <tool> -ArgsFile args.json` (UTF-8 JSON), `darwin.ps1 -List`. The radar's instructions through Darwin are in [docs/RADAR.md](docs/RADAR.md).

The MCP bridge (`mcp_server.py`, stdio) proxies every call to the running app with the token in `data/mcp-token`. It never starts the app: while Darwin is stopped it lists the tools from the package's own catalogue and a call answers `not_running`. Start Darwin explicitly from the Hoard Hub (Start on its card, or `POST http://127.0.0.1:8810/api/apps/darwin/start`), with `Iniciar Darwin's Hoard.cmd` or with `python -m darwin_hoard`.

## Running

```
Iniciar Darwin's Hoard.cmd
```

or from the Hoard Hub. Python 3.11+, FastAPI, the vendored Hoard Link copy in `darwin_hoard/hoard_link`. Data in `data/darwin.db` (SQLite). Settings in `data/settings.json` (radar folder, Faustus URL, WhatsApp chat JID and sync interval, tree refresh interval).

## Tests

```
.venv\Scripts\python.exe -m pytest
```

Temporary data folders and fixtures only: no real chat, hub or repository is touched.

## Skills for the agents that connect

This app carries procedures from the skill library of the family's workspace for the agents that connect to it: `discovery-to-capability`, `learn-this-repo`, `codebase-onboarding`, `search-first`, `reuse-before-you-write`, `deep-research`. They are named in what an agent reads on connecting, read with `skills_list` and `skill_read`, searched and assigned with `skills_library` and `skills_assign`, and offered as prompts. The person chooses them on the skills page (`/api/agent/skills/page`) or in the hub's Skills tab; the `skills` block of `faustus-plugin.json` holds what the app asks for by default.
