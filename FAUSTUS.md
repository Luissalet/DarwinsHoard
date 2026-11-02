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
| Re-read the legacy radar files and Ágora | `darwin_import_legacy` (idempotent) |

## Rules

- Never fold states: proposal, implementation, verification and operation are separate axes.
- A declared delivery is not proof; `evidence.commit_ancestry = integrated` is code proof, not a functional test.
- WhatsApp access is read only through Faustus's bridge; nothing is sent or marked as read.

## What it cannot do (yet)

- Fitness ranking of discoveries, gap-driven radar searches and Brain export (see OBJETIVOS.md).
- Read WhatsApp history the bridge never received.
