"""The six suits of research proposal 36, as a starting point.

Capability keys point at nodes of the tree where a Hoard or tool plausibly covers the step. None of them is marked as
implemented here: backing needs evidence (``darwin_capability_mark``), so a freshly seeded library reads ``proposed`` or
``partial`` until somebody attaches a commit, a test or a QA file. A step with no key is a capability that does not exist
yet and says why. Seeds are inserted once and never overwrite a suit that was edited; deleting a seed keeps it deleted."""

from __future__ import annotations

from typing import Any

from .store import Store
from .suits import save_suit

ORIGIN = "research proposal 36"


def _op(name: str, key: str = "", note: str = "", missing: str = "") -> dict[str, Any]:
    return {"name": name, "capability_key": key, "note": note, **({"missing_reason": missing} if missing else {})}


SEEDS: list[dict[str, Any]] = [
    {
        "slug": "repository-intake", "name": "Repository intake",
        "objective": "Decide, for a repository or link someone found, whether it was seen before, what it offers and which app (if any) should take it.",
        "inputs": [{"name": "repository or link", "kind": "url", "identity": "canonical URL or owner/repo; GitHub id when known"},
                   {"name": "note", "kind": "text", "identity": "who wrote it, where and when"}],
        "concepts": [{"term": "discovery", "meaning": "a source that could improve Faustus or a Hoard"},
                     {"term": "genealogy", "meaning": "appearances, proposals per app and deliveries of one discovery"}],
        "operations": [
            _op("Check whether it was seen", "tool:darwin:darwin_add", "Returns the existing record, never duplicates."),
            _op("Read its history", "tool:darwin:darwin_source"),
            _op("Find which app already covers it", "tool:darwin:darwin_capability_find"),
            _op("Record the proposal for an app", "tool:darwin:darwin_propose"),
            _op("Read the repository itself (README, licence, activity)", "", missing="No Hoard reads and summarises a repository on demand."),
        ],
        "views": [{"name": "Discovery genealogy", "shows": "captures, proposals, deliveries and proof in the main branch"},
                  {"name": "Who does this", "shows": "matching capabilities with their path in the tree"}],
        "acceptance": [{"id": "no-duplicate", "kind": "executable", "check": "the discovery exists once under its canonical key"},
                       {"id": "app-named", "kind": "executable", "check": "the deliverable names a target app or says none fits", "regex": "(?i)app|ninguna"},
                       {"id": "covered-check", "kind": "judge", "check": "the covered-or-not claim cites a capability node"}],
        "recipe": [{"step": "Add the link", "op": "Check whether it was seen"}, {"step": "Read what is already known", "op": "Read its history"},
                   {"step": "Ask which app covers it", "op": "Find which app already covers it"},
                   {"step": "Write a one-paragraph verdict and propose", "op": "Record the proposal for an app"}],
        "judgement": [{"point": "Is it really covered by an existing capability?", "why": "names in the tree are not proof of function"},
                      {"point": "Which app is the right home?", "why": "several apps can plausibly take it"}],
    },
    {
        "slug": "small-migration", "name": "Small migration",
        "objective": "Move a small codebase or configuration from one framework, version or layout to another without changing its behaviour.",
        "inputs": [{"name": "source tree", "kind": "folder", "identity": "path plus commit hash"},
                   {"name": "target description", "kind": "text", "identity": "framework and version"},
                   {"name": "existing tests", "kind": "folder", "identity": "path plus file hashes"}],
        "concepts": [{"term": "behavioural equivalence", "meaning": "the same tests pass before and after"},
                     {"term": "migration step", "meaning": "one reversible change with its own check"}],
        "operations": [
            _op("Read and edit the code", "faustus:native", "Faustus's own tools."),
            _op("Run the project's tests before and after", "", missing="No tool records a before/after test run as comparable evidence."),
            _op("Show the diff per step", "", missing="No per-step diff view with a rollback."),
            _op("Review the result with a second model", "app:pygmalion", "Judges and the logit judge exist in the evaluation module."),
        ],
        "views": [{"name": "Step list", "shows": "each step, its check and its result"}, {"name": "Test delta", "shows": "tests passing before and after"}],
        "acceptance": [{"id": "tests-green", "kind": "executable", "check": "the same tests pass on the migrated tree"},
                       {"id": "no-leftovers", "kind": "executable", "check": "no reference to the old framework remains", "regex": "^$"},
                       {"id": "notes", "kind": "judge", "check": "the migration notes explain every behavioural risk"}],
        "recipe": [{"step": "Run the tests and keep the result"}, {"step": "Migrate one step at a time"}, {"step": "Run the tests after each step"},
                   {"step": "Write the migration notes"}],
        "judgement": [{"point": "Is a failing test a real regression or an outdated test?", "why": "only reading the intent tells them apart"}],
    },
    {
        "slug": "web-3d-product-model", "name": "Web 3D product model",
        "objective": "Turn product photos and measurements into a 3D model that can be shown on a web page and, if wanted, printed.",
        "inputs": [{"name": "product photos", "kind": "images", "identity": "file hashes"},
                   {"name": "measurements", "kind": "table", "identity": "unit and source of each value"}],
        "concepts": [{"term": "scale reference", "meaning": "a measured length that fixes the model's size"},
                     {"term": "web budget", "meaning": "maximum triangles and file size for smooth display"}],
        "operations": [
            _op("Build a printable model", "app:gulliver", "Makes 3D models of places; products are a different input."),
            _op("Critique the render", "app:vitruvius", "Design studio with render critique."),
            _op("Export for the web (glTF) within the budget", "", missing="No tool exports a web-ready model and checks its triangle and size budget."),
            _op("Reconstruct a shape from photos", "", missing="No photo-to-model step exists in the family."),
        ],
        "views": [{"name": "Turntable", "shows": "the model from several sides next to the photos"}, {"name": "Budget", "shows": "triangles and file size against the limit"}],
        "acceptance": [{"id": "file", "kind": "executable", "check": "the model file exists", "path": "out/model.glb"},
                       {"id": "size", "kind": "executable", "check": "file size within the web budget (MB)", "max": 5},
                       {"id": "dimensions", "kind": "executable", "check": "bounding box matches the measurements within tolerance", "tolerance": 0.02},
                       {"id": "likeness", "kind": "judge", "check": "the render looks like the photographed product"}],
        "recipe": [{"step": "Fix the scale from a measurement"}, {"step": "Build the model"}, {"step": "Optimise to the web budget"}, {"step": "Render and compare with the photos"}],
        "judgement": [{"point": "Does the render look like the product?", "why": "no automatic metric replaces looking at it"}],
    },
    {
        "slug": "part-budget", "name": "Part budget",
        "objective": "From a list of parts and conditions, produce a budget with the cheapest valid combination and the sources of every price.",
        "inputs": [{"name": "parts list", "kind": "table", "identity": "part number or description plus quantity"},
                   {"name": "constraints", "kind": "text", "identity": "budget cap, compatibility, delivery date"}],
        "concepts": [{"term": "valid combination", "meaning": "a choice of parts that satisfies every constraint"},
                     {"term": "price source", "meaning": "where and when a price was read"}],
        "operations": [
            _op("Choose parts under constraints", "app:dantzig", "Configurator and planner."),
            _op("Read current prices", "app:tantalus", "Product and price watcher."),
            _op("Read quotes and invoices", "app:kafka", "Paperwork reader."),
            _op("Explain why a combination is optimal", "", missing="No step turns the solver's result into a reviewed explanation."),
        ],
        "views": [{"name": "Budget table", "shows": "part, quantity, unit price, source and date"}, {"name": "Alternatives", "shows": "the next best valid combinations"}],
        "acceptance": [{"id": "total", "kind": "executable", "check": "the total equals the sum of the lines", "tolerance": 0.01},
                       {"id": "cap", "kind": "executable", "check": "the total is within the cap"},
                       {"id": "sources", "kind": "executable", "check": "every price line names a source", "regex": "(?i)https?://|factura|presupuesto"},
                       {"id": "reasoning", "kind": "judge", "check": "the choice is justified against the alternatives"}],
        "recipe": [{"step": "Normalise the parts list"}, {"step": "Fetch prices with their source"}, {"step": "Solve under the constraints"}, {"step": "Write the budget and the alternatives"}],
        "judgement": [{"point": "Are two listed parts the same part?", "why": "descriptions differ between suppliers"}],
    },
    {
        "slug": "contradictory-documentation", "name": "Contradictory documentation",
        "objective": "Given documents about the same system that disagree, list each contradiction with its sources and say which statement to trust and why.",
        "inputs": [{"name": "documents", "kind": "files", "identity": "path, hash and date of each"},
                   {"name": "system under study", "kind": "text", "identity": "name and version"}],
        "concepts": [{"term": "claim", "meaning": "one checkable statement with its location"},
                     {"term": "contradiction", "meaning": "two claims that cannot both hold"},
                     {"term": "authority", "meaning": "which source wins when claims clash: code, tests, newest, official"}],
        "operations": [
            _op("Read and index the documents", "app:kafka", "Paperwork and deadlines reader."),
            _op("Keep research cases with their sources", "app:atlas", "Research cases."),
            _op("Extract claims and compare them pairwise", "", missing="No tool extracts claims with locations and finds contradictions."),
            _op("Check a claim against the code or a test", "faustus:native", "Faustus's own tools."),
        ],
        "views": [{"name": "Contradiction list", "shows": "claim A, claim B, locations, verdict"}, {"name": "Source ranking", "shows": "which document was right most often"}],
        "acceptance": [{"id": "report", "kind": "executable", "check": "the report file exists", "path": "out/contradictions.md"},
                       {"id": "locations", "kind": "executable", "check": "every contradiction cites two locations", "regex": "(?s)\\S+:\\d+.*\\S+:\\d+"},
                       {"id": "verdicts", "kind": "judge", "check": "each verdict is supported by a source of higher authority"}],
        "recipe": [{"step": "Index the documents"}, {"step": "Extract claims"}, {"step": "Compare claims on the same topic"}, {"step": "Verify against code or tests"}, {"step": "Write verdicts"}],
        "judgement": [{"point": "Do two claims really contradict, or do they speak of different versions?", "why": "dates and versions are often implicit"},
                      {"point": "Which source has authority?", "why": "depends on the system"}],
    },
    {
        "slug": "data-to-product", "name": "Data to product",
        "objective": "Take a raw dataset and deliver a usable product from it (report, dashboard or small app), with the data quality stated.",
        "inputs": [{"name": "dataset", "kind": "file", "identity": "path, hash, row count and column list"},
                   {"name": "intended use", "kind": "text", "identity": "who uses it and for what"}],
        "concepts": [{"term": "data model", "meaning": "tables, keys and meaning of each column"},
                     {"term": "quality finding", "meaning": "a measured problem: missing values, duplicates, outliers"}],
        "operations": [
            _op("Ingest and model the data", "app:nightingale", "Data workbench."),
            _op("Present the result", "app:cicero", "Presentation maker."),
            _op("Measure data quality and write findings", "", missing="No step records quality findings as part of the deliverable."),
            _op("Run the acceptance checks on the deliverable", "", missing="No runner for executable acceptance criteria exists in the family."),
        ],
        "views": [{"name": "Data profile", "shows": "columns, types, missing values, duplicates"}, {"name": "Deliverable preview", "shows": "the product as the user will see it"}],
        "acceptance": [{"id": "deliverable", "kind": "executable", "check": "the deliverable file exists", "path": "out/report.html"},
                       {"id": "schema", "kind": "executable", "check": "the summary JSON follows its schema"},
                       {"id": "totals", "kind": "executable", "check": "totals in the report match the data", "tolerance": 0.001},
                       {"id": "readable", "kind": "judge", "check": "a reader who did not see the data understands the conclusions"}],
        "recipe": [{"step": "Profile the data"}, {"step": "Model it"}, {"step": "Build the product"}, {"step": "Run the checks and write the quality notes"}],
        "judgement": [{"point": "Which anomalies are errors and which are real?", "why": "needs knowledge of the domain"}],
    },
]


def seed(store: Store) -> dict[str, int]:
    """Insert the seeds that were never inserted. Idempotent; remembers in ``meta`` so a deleted seed does not come back."""
    done = set(store.get_meta("suits_seeded", []) or [])
    added = 0
    for s in SEEDS:
        if s["slug"] in done:
            continue
        if not store.one("SELECT id FROM suits WHERE slug=?", (s["slug"],)):
            save_suit(store, {**s, "origin": ORIGIN}, by="seed")
            added += 1
        done.add(s["slug"])
    store.set_meta("suits_seeded", sorted(done))
    return {"added": added, "total": len(SEEDS)}
