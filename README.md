# Darwin's Hoard

Keeps every discovery that could improve Faustus or one of the Hoards (a GitHub repository, an article, a paper, a reel, a loose idea) together with where it came from, what was proposed for which app, what was delivered, and the capability tree of the whole family. It answers two questions before anyone spends time on a link: *have we seen this already, and what happened to it?* and *which app already does this?*

Port **5233**, id `darwin`, part of the Hoard family (Faustus copilot, Hoard Hub window, MCP bridge).

## What it shows

| View | What is in it |
|---|---|
| **Resumen** | Counts, discoveries per state, apps with most proposals, where discoveries come from, deliveries (declared and proven in the main branch), the Gittrend chat sync and the imports with the file hash of each. |
| **Historial** | Every discovery, filterable by text, `owner/repo`, URL or radar number, state, app, origin and "only the ones I marked 📌", in several orders. Each one opens its genealogy: appearances with file and line, proposals per app with their history, deliveries with commits and whether the commit is in the main branch. Proposal states can be changed and new proposals made from there. |
| **Bandeja** | Captures that have no source yet (a chat note, a screenshot without a link), with the image and the text the OCR read in it. They are never dropped; one click turns them into a discovery. **Leer capturas (OCR)** reads the unread screenshots with the family's OCR (Kafka's engine) and links the URLs it finds and the `owner/repo` names GitHub confirms; it also runs on its own after a chat sync brings new messages. |
| **Árbol** | Faustus (root) > Hoard Hub > Hoards > absorbed modules > capabilities > the tools Faustus really sees, with evidence (*declarada* from a manifest, *viva* from Faustus's tool catalogue) and state (*disponible*, *detenida*). A "¿Quién hace…?" search answers which apps already cover something, with the path of each match. |
| **Novedades** | New discoveries, state changes and deliveries since the last visit (or the last day, week or month). |
| **Carencias** | Things that are wanted and no app does yet, with the condition that would make them possible. |

The **Añadir** box in the header takes a URL, `owner/repo` or free text and returns the existing record when there is one.

## Data model

capture → source → idea → proposal (idea × app) → delivery (proposal × repository/commit/Ágora task) → evidence.

State axes are kept apart and never folded into one flag:

- proposal: `pendiente`, `investigando`, `debatida`, `aceptada`, `aplazada`, `descartada`, `cubierta`;
- implementation per delivery: `sin_implementar`, `parcial`, `integrada`, `sustituida`;
- verification per delivery: `documentada`, `probada`, `recomprobar`, `desconocida`;
- operation per tree node: `disponible`, `detenida`, `desconocida`.

What a document or a person declared is stored as declared; the commit check adds `evidence.commit_ancestry` (`integrated`, `not_in_main`, or why it could not be checked) without overwriting it. A commit in the main branch is code evidence, not a functional test. Every state change keeps the previous value in `history`.

A source is identified by `repo:owner/name` (lower case; the GitHub id, when known, joins renamed repositories), `url:<canonical URL>` (tracking parameters, `www.`, fragments and trailing slashes removed; posts on X, Instagram, TikTok, LinkedIn, Reddit and similar lose every query parameter, and twitter.com becomes x.com; older keys are merged on start and kept as aliases) or `idea:<hash>`.

## Where the data comes from

| Origin | How |
|---|---|
| Radar files | `RADAR_GITTREND.md`, `IMPLEMENTACION_RADAR.md`, `GUIA_IMPLEMENTACION.md` (folder set in settings) and the 426-510 entries exported to `radar-ideas.md`. Idempotent: importing twice adds nothing; an edited line becomes a second appearance. |
| Ágora | Tasks of every space that cite `radar #N` (or carry a `darwin:<id>` label) become proposals for their space's app; a done task with commits adds a declared delivery in the repository the task names. |
| WhatsApp «Gittrend» | Read only, through Faustus's WhatsApp bridge (`/api/whatsapp/message-page`), page by page with a cursor; nothing is sent or marked as read, and a second sync repeats nothing. Coverage is what the bridge keeps (60 days), not the phone's whole history. Screenshots go to the inbox and through the OCR. |
| Other apps and agents | `darwin_ingest` (Links, Talos OCR, a chat) and `darwin_add`. |
| Capability tree | The hub's `/api/apps`, Faustus's `/api/tools/catalog`, and the `faustus-plugin.json` manifests when the hub is down. |

## Tools (MCP and the page)

`darwin_overview`, `darwin_find`, `darwin_source`, `darwin_add`, `darwin_propose`, `darwin_set_state`, `darwin_tree`, `darwin_capability_find`, `darwin_tree_refresh`, `darwin_gaps`, `darwin_gap_add`, `darwin_changes_since`, `darwin_inbox`, `darwin_ingest`, `darwin_verify_deliveries`, `darwin_whatsapp_chats`, `darwin_sync_whatsapp`, `darwin_read_screenshots`, `darwin_import_legacy`.

The MCP bridge (`mcp_server.py`, stdio) proxies every call to the running app with the token in `data/mcp-token` and starts the app when nothing answers.

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
