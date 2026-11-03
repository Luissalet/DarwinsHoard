# The radar, through Darwin

The scheduled radar task («Radar diario de ideas para Faustus y los Hoards») is disabled since 11-10-2026 and its instructions still
point at the old folders and at loose Markdown files. This is the version that registers every finding in Darwin. It replaces the
task's instructions once Luis approves the change (the scheduled-task edit needs his permission).

Agents call Darwin from PowerShell with `darwin.ps1` (JSON arguments in a UTF-8 file):

```
& "E:\Development\IA\Hoards\Faustusables\Darwin's Hoard\darwin.ps1" darwin_add -ArgsFile add.json
& "E:\Development\IA\Hoards\Faustusables\Darwin's Hoard\darwin.ps1" -List
```

## Instructions for the scheduled task

1. **Context.**
   - Darwin: `darwin_radar_plan` first. It ranks the open gaps and gives each its GitHub and web queries, the discoveries already
     held that may answer it and whether the tree may cover it. `notify: false` means nothing changed since the last plan; if
     `darwin_radar_run` (the plan's first three gaps on GitHub) then finds no new repository either, stop here and report nothing.
   - Then `darwin_overview` and `darwin_changes_since`; `darwin_watches_check` for the saved questions («avísame cuando…»).
   - Ágora: `hb "radar"`, `inbox`, `board`.
   - Read `D:\LocalAI\CRITERIOS.md` and `AGENTS.md`.
2. **Sweep.** Three cheap subagents with WebFetch/WebSearch:
   - gittrend.io trending pages;
   - trendshift.io, plus the plan's queries for the open gaps and the Hoards' domains;
   - Hacker News, llama.cpp/Ollama releases, arXiv cs.CL/cs.AI.
   
   A page that fails is skipped. Only features: no security, permissions, telemetry or caps (Luis, 11-10-2026).
3. **Dedupe and classify in Darwin.**
   - Every candidate goes through `darwin_add` with `{"text": url, "channel": "radar", "note": what it does and could bring}`. `existing: true` means it was already seen: report its state and move on.
   - Coverage: `darwin_coverage` with the discovery's id (covered / partial / gap with the matching nodes), `darwin_capability_find`
     or `darwin_ask`, plus a grep in the target repository.
   - New ones: `darwin_propose` with `{source_id, target, reason}`, or `darwin_triage` with `{"channel": "radar"}`.
   - A new Hoard: `darwin_gap_add`, plus a decision thread in the Ágora with `escalate`.
4. **Ágora.**
   - One task per proposal with concrete work: `add "<App>: <what> (darwin #<source_id>)"`. Then link it back with `darwin_propose` (`agora_space`, `agora_task`).
   - A day thread listing the tasks.
   - `darwin_discuss` opens the debate of a proposal.
5. **Implementation.** One or two open radar tasks, directly in the real repository on its main branch (no worktrees or copies),
   with tests and a live check.
   - Commits as Luissalet, in English, without trailers; stage only your own files; never push.
   - Submit in the Ágora with the commits.
   - Once integrated, `darwin_set_state` with the commit.
6. **Close.** Six lines at most: discoveries registered (new and already seen), proposals, Ágora tasks, implemented (sha).

Paths since 29-10-2026:
- Faustus: `E:\Development\IA\Faustus`, port 7000.
- Hoards: `E:\Development\IA\Hoards\Faustusables\<Hoard>`.
- Darwin: port 5233.
