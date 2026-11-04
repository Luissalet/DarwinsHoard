"""Tools for assistants and for the UI (one catalogue: ``/api/agent/*`` for the MCP bridge, ``/api/ui/call`` for the page)."""

from __future__ import annotations

import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from . import backing, coverage, query, reconcile, suit_seeds, suits, tree, views, watches
from .canon import canonical_url, extract_refs, repo_of, source_key
from .errors import DarwinError
from .hoard_link.agentkit import Empty, Tool, ann
from .hoard_link.agentkit import call_tool as _call_tool
from .hoard_link.agentkit import tool_catalog as _catalog
from .hoard_link.agentkit import uncapped  # noqa: F401 - re-exported for the UI routes
from .services import Services
from .store import IMPLEMENTATION_STATES, PROPOSAL_STATES, VERIFICATION_STATES

AGENT_INSTRUCTIONS = """Darwin's Hoard keeps every discovery (GitHub repository, article, paper, video, idea) that could improve Faustus or a Hoard, where it came from (radar line, Ágora task, chat message, screenshot), what was proposed for which app, what was delivered (commit, task) and the capability tree of the family: Faustus > Hoard Hub > Hoards > absorbed modules > capabilities > tools.
Before analysing a repository or idea, call darwin_add (or darwin_find): if it already exists you get its history and states and must not redo the work. darwin_source gives one discovery's full genealogy (captures with provenance, proposals per target app with their history, deliveries with commits). darwin_tree / darwin_capability_find answer «which app already does X» with evidence (declarada = manifest, viva = tool Faustus sees, probada = tested). darwin_propose records a proposal for a target app; darwin_set_state changes a state with history (never invent a delivered state: «integrada» needs a commit or a done Ágora task). darwin_gap_add records something Luis wants and no app does yet.
States are separate axes: proposal (pendiente, investigando, debatida, aceptada, aplazada, descartada, cubierta), implementation per delivery (sin_implementar, parcial, integrada, sustituida), verification (documentada, probada, recomprobar, desconocida)."""


def _d(first: str, detail: str = "", synonyms: str = "") -> str:
    return "\n".join(p for p in (first, detail, ("Sinónimos: " + synonyms) if synonyms else "") if p)


class FindArgs(BaseModel):
    query: str = Field("", max_length=300, description="Text, owner/repo, URL or radar number (#123).")
    state: str = Field("", max_length=30, description="Aggregate or proposal/implementation state to filter on.")
    target: str = Field("", max_length=60, description="App id (faustus, links, silver, hoardhub…).")
    channel: str = Field("", max_length=30, description="Capture channel: radar, radar-ideas, tracker, guide, agora, whatsapp, links, talos, agent, manual.")
    kind: str = Field("", max_length=20)
    pinned: Optional[bool] = Field(None, description="Only what Luis marked himself (📌).")
    radar_from: Optional[int] = Field(None, ge=0, le=100000)
    radar_to: Optional[int] = Field(None, ge=0, le=100000)
    order: Literal["recent", "oldest", "radar", "radar_desc", "captures", "title", "fitness"] = Field(
        "recent", description="fitness = open discoveries most worth a look first (gaps, reappearances, stars, licence, recency).")
    limit: int = Field(30, ge=1, le=500)
    offset: int = Field(0, ge=0)
    saved: str = Field("", max_length=60, description="Name of a saved filter (darwin_saved_filters) to apply underneath the other arguments.")


class CoverageArgs(BaseModel):
    source_id: Optional[int] = Field(None, ge=1, description="A discovery to check.")
    text: str = Field("", max_length=4000, description="Or a free text: an idea, a gap, a repository description.")


class RadarPlanArgs(BaseModel):
    limit: int = Field(10, ge=1, le=100)
    remember: bool = Field(True, description="Store this plan as the baseline, so the next one only reports what changed (notify).")


class RadarRunArgs(BaseModel):
    top: int = Field(3, ge=1, le=10, description="How many of the plan's first gaps to search.")
    per_gap: int = Field(5, ge=1, le=20, description="Repositories per search.")
    add: bool = Field(False, description="Register the repositories Darwin did not know as discoveries (channel radar).")
    gap_ids: list[int] = Field(default_factory=list, description="Search these gaps instead of the plan's first ones.")


class WatchAddArgs(BaseModel):
    question: str = Field(..., min_length=3, max_length=500, description="The question to keep, e.g. «¿hay algo para leer PDFs escaneados?».")
    note: str = Field("", max_length=1000)
    target: str = Field("", max_length=60, description="App it is about, if any.")


class WatchUpdateArgs(BaseModel):
    id: int = Field(..., ge=1)
    state: Literal["", "activa", "pausada"] = ""
    delete: bool = False
    clear_news: bool = Field(False, description="Mark the news as read.")


class ProposalsArgs(BaseModel):
    state: str = Field("", max_length=30)
    target: str = Field("", max_length=60)
    origin: str = Field("", max_length=30, description="luis, agent, agora, radar, tracker…")
    query: str = Field("", max_length=200)
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class FiltersArgs(BaseModel):
    action: Literal["list", "save", "delete"] = "list"
    name: str = Field("", max_length=60)
    filter: dict[str, Any] = Field(default_factory=dict, description="query, state, target, channel, kind, pinned, order (as darwin_find).")


class PanelArgs(BaseModel):
    app: str = Field("", max_length=60, description="App id.")
    space: str = Field("", max_length=60, description="Or the Ágora space / Faustus project slug (research = the whole family).")
    project: str = Field("", max_length=200, description="Or the Faustus project name.")
    limit: int = Field(8, ge=1, le=30)


class SourceArgs(BaseModel):
    id: Optional[int] = Field(None, ge=1)
    key: str = Field("", max_length=500, description="owner/repo, URL or source key.")
    radar_no: Optional[int] = Field(None, ge=0)


class AddArgs(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000, description="URL, owner/repo or free text (a message, an OCR'd screenshot).")
    note: str = Field("", max_length=2000, description="Why it matters / what to look at.")
    target: str = Field("", max_length=60, description="App it is proposed for, if known.")
    channel: Literal["agent", "manual", "links", "talos", "whatsapp"] = "agent"
    author: str = Field("", max_length=60)


class ProposeArgs(BaseModel):
    source_id: int = Field(..., ge=1)
    target: str = Field(..., min_length=1, max_length=60)
    state: Literal[PROPOSAL_STATES] = "pendiente"  # type: ignore[valid-type]
    reason: str = Field("", max_length=2000)
    capability: str = Field("", max_length=200, description="Capability key in the tree, if it maps to one.")
    agora_space: str = Field("", max_length=60)
    agora_task: Optional[int] = Field(None, ge=1)


class SetStateArgs(BaseModel):
    entity: Literal["proposals", "deliveries"]
    id: int = Field(..., ge=1)
    field: Literal["state", "implementation", "verification"]
    value: str = Field(..., min_length=1, max_length=30)
    note: str = Field("", max_length=1000)
    by: str = Field("agent", max_length=60)


class TreeArgs(BaseModel):
    root: str = Field(tree.ROOT, max_length=300, description="Node key: faustus, hoardhub, app:<id>, cap:<app>:<cap>.")
    depth: int = Field(2, ge=0, le=8)
    tools: bool = Field(True, description="Include tool leaves.")


class CapFindArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(15, ge=1, le=60)
    tools: bool = True


class GapArgs(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    detail: str = Field("", max_length=4000)
    target: str = Field("", max_length=60)
    capability: str = Field("", max_length=200)
    watch: str = Field("", max_length=500, description="What would make it solvable (a condition to re-check).")


class SuitsArgs(BaseModel):
    status: Literal["", "proposed", "partial", "backed", "evaluated"] = Field(
        "", description="Only suits in this status. proposed: nothing backed; partial: some operations backed; backed: all required operations exist "
                        "AND carry evidence; evaluated: results from Pygmalion imported.")


class SuitRef(BaseModel):
    slug: str = Field(..., min_length=3, max_length=64, description="Suit id, e.g. repository-intake.")


class SuitSaveArgs(BaseModel):
    slug: str = Field(..., min_length=3, max_length=64, description="Lower case letters, digits and hyphens.")
    name: Optional[str] = Field(None, max_length=200)
    objective: Optional[str] = Field(None, max_length=3000)
    inputs: Optional[list[dict[str, Any]]] = Field(None, description="[{name, kind, identity}]: what comes in and how each input is identified.")
    concepts: Optional[list[dict[str, Any]]] = Field(None, description="[{term, meaning}]: domain concepts.")
    operations: Optional[list[dict[str, Any]]] = Field(
        None, description="[{name, capability_key, required?, note?, missing_reason?}]: the operations, each pointing to a node of the capability tree "
                          "(darwin_tree). Leave capability_key empty for a capability that does not exist yet and say why.")
    views: Optional[list[dict[str, Any]]] = Field(None, description="[{name, shows}]: views to inspect while working.")
    acceptance: Optional[list[dict[str, Any]]] = Field(None, description="[{id, check, kind: executable|judge, ...}]: acceptance criteria of the deliverable.")
    recipe: Optional[list[dict[str, Any]]] = Field(None, description="[{step, op?}]: execution recipe.")
    judgement: Optional[list[dict[str, Any]]] = Field(None, description="[{point, why}]: where a model has to judge.")
    origin: Optional[str] = Field(None, max_length=300)
    proposal: Optional[str] = Field(None, max_length=300, description="Research proposal this suit comes from.")


class EvidenceItem(BaseModel):
    kind: Literal["commit", "test", "qa_file"]
    ref: str = Field(..., min_length=1, max_length=300, description="Commit hash (or repo@hash), test path (file::name) or QA file path.")
    note: str = Field("", max_length=300)


class MarkArgs(BaseModel):
    key: str = Field(..., min_length=1, max_length=300, description="Capability node key (darwin_tree / darwin_capability_find).")
    implemented: bool = Field(True, description="false removes the mark.")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="At least one link is required to mark a node implemented.")
    note: str = Field("", max_length=1000)
    by: str = Field("agent", max_length=60)


class ReconcileArgs(BaseModel):
    confirm_ids: list[int] = Field(default_factory=list, description="Gaps a person checked and confirms as resolved (state resuelta).")
    dismiss_ids: list[int] = Field(default_factory=list, description="Flagged gaps that are NOT answered by the capability: keep open, do not flag again.")
    by: str = Field("agent", max_length=60)


class SuitEvalImportArgs(BaseModel):
    result: Optional[dict[str, Any]] = Field(None, description="The evaluation exported by Pygmalion's Hoard (format pygmalion-suit-eval/1).")
    path: str = Field("", max_length=1000, description="Or the path of the JSON file Pygmalion exported.")
    slug: str = Field("", max_length=64, description="Suit to attach it to; default: the one named in the file.")


class ImportArgs(BaseModel):
    inspiration_dir: str = Field("", max_length=500)
    radar_ideas: str = Field("", max_length=500)
    agora: bool = True


class InboxArgs(BaseModel):
    channel: str = Field("", max_length=30)
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class ChatsArgs(BaseModel):
    query: str = Field("", max_length=100, description="Part of the chat name, e.g. Gittrend.")


class AskArgs(BaseModel):
    question: str = Field(..., min_length=3, max_length=500, description="A question in plain words, e.g. «¿qué tenemos para transcribir reuniones?».")


class LoginArgs(BaseModel):
    site: Literal["x", "instagram", "threads", "tiktok", "reddit", "facebook", "youtube"]
    finish: bool = Field(False, description="Luis says he finished signing in: save the session now.")
    cancel: bool = Field(False, description="Close the sign-in window.")


class PostsArgs(BaseModel):
    limit: int = Field(30, ge=1, le=300)


class DiscussArgs(BaseModel):
    proposal_id: int = Field(..., ge=1)
    note: str = Field("", max_length=4000, description="Optional note to add (posted by the agent darwin, marked as Luis's).")


class TriageArgs(BaseModel):
    channel: str = Field("", max_length=30, description="Only discoveries that arrived through this channel (e.g. whatsapp).")
    limit: int = Field(20, ge=1, le=200)


class OcrArgs(BaseModel):
    limit: int = Field(60, ge=1, le=500, description="How many unread screenshots to read in this call.")


class SyncArgs(BaseModel):
    chat: str = Field("", max_length=200, description="Exact JID; empty = the chat chosen in settings.")
    max_pages: int = Field(50, ge=1, le=500)


class IngestArgs(BaseModel):
    channel: Literal["links", "talos", "whatsapp", "manual", "agent"] = "agent"
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=2000,
                                          description="Each with a stable capture_key and text/url/at/author/chat/attachment/provenance.")


class SinceArgs(BaseModel):
    since: Optional[float] = Field(None, description="Epoch seconds; default: 7 days ago.")
    limit: int = Field(200, ge=1, le=1000)


class RepoAliasArgs(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Repository name as deliveries use it, e.g. «Galton's Hoard».")
    repo: str = Field("", max_length=200, description="Today's repository name in the hub's inventory, e.g. «Pygmalion's Hoard».")
    path: str = Field("", max_length=500, description="Or a local folder that is a git repository.")
    subdir: str = Field("", max_length=300, description="Folder inside it where a folded app lives, e.g. galton_hoard.")
    search: bool = Field(False, description="Old umbrella name: look for its commits in every repository.")
    remove: bool = Field(False, description="Drop Luis's entry for this name (a built-in alias comes back).")


def _find(s: Services, a: FindArgs) -> dict[str, Any]:
    args = a.model_dump()
    saved = args.pop("saved")
    if saved:
        try:
            args = views.apply_filter(s.store, saved, args)
        except KeyError as exc:
            raise DarwinError("not_found", str(exc), "List them with darwin_saved_filters.") from exc
    return query.find(s.store, **args)


def _coverage(s: Services, a: CoverageArgs) -> dict[str, Any]:
    if not a.source_id and not a.text.strip():
        raise DarwinError("invalid", "Give a source_id or a text.")
    try:
        return coverage.classify(s.store, source_id=a.source_id, text=a.text)
    except KeyError as exc:
        raise DarwinError("not_found", str(exc)) from exc


def _watch_update(s: Services, a: WatchUpdateArgs) -> dict[str, Any]:
    try:
        return watches.set_state(s.store, a.id, state=a.state, delete=a.delete, clear_news=a.clear_news)
    except KeyError as exc:
        raise DarwinError("not_found", str(exc)) from exc


def _filters(s: Services, a: FiltersArgs) -> dict[str, Any]:
    try:
        if a.action == "save":
            return views.save_filter(s.store, a.name, a.filter)
        if a.action == "delete":
            return views.delete_filter(s.store, a.name)
    except KeyError as exc:
        raise DarwinError("not_found", str(exc)) from exc
    except ValueError as exc:
        raise DarwinError("invalid", str(exc)) from exc
    return {"filters": views.saved_filters(s.store)}


def _source(s: Services, a: SourceArgs) -> dict[str, Any]:
    g = query.genealogy(s.store, source_id=a.id, key=a.key, radar_no=a.radar_no)
    if not g:
        raise DarwinError("not_found", "No such discovery.", "Search with darwin_find.")
    return g


def _add(s: Services, a: AddArgs) -> dict[str, Any]:
    """One capture for the whole text; one source per URL/repository found (bare owner/name only as a candidate)."""
    refs = extract_refs(a.text)
    text = a.text.strip()
    if not refs and (repo_of(text) or text.startswith("http")):
        refs = [{"key": source_key(url=text if text.startswith("http") else "", repo=repo_of(text) or ""), "url": canonical_url(text) if text.startswith("http") else f"https://github.com/{repo_of(text)}", "kind": "url"}]
    capture_key = f"{a.channel}:{source_key(title=text)[5:]}"
    cid, created = s.store.add_capture(capture_key=capture_key, channel=a.channel, text=text, author=a.author or a.channel,
                                       declared={"note": a.note, "target": a.target} if (a.note or a.target) else None,
                                       provenance={"via": "darwin_add", "at": time.time()})
    results = []
    for ref in refs:
        existed = s.store.source_by_key(ref["key"])
        sid = s.store.upsert_source(url=ref["url"], title=ref.get("raw", ""), summary=a.note,
                                    meta={"candidate": True} if ref.get("kind") == "candidate" else None)
        s.store.link_capture(cid, sid)
        if a.target:
            src = s.store.source(sid)
            s.store.upsert_proposal(key=f"{src['key']}->{a.target}", source_id=sid, target=a.target, state="pendiente",
                                    origin=a.channel if a.channel != "manual" else "luis", reason=a.note)
        g = query.genealogy(s.store, source_id=sid)
        results.append({"existing": bool(existed), "candidate": ref.get("kind") == "candidate", "source": g["source"],
                        "state": g["state"], "proposals": g["proposals"], "deliveries": g["deliveries"]})
    if not refs:
        sid = s.store.upsert_source(title=text[:200], kind="idea", summary=a.note)
        s.store.link_capture(cid, sid)
        results.append({"existing": False, "candidate": False, "source": s.store.source(sid), "state": "sin_propuesta"})
    return {"capture_id": cid, "capture_created": created, "sources": results}


def _propose(s: Services, a: ProposeArgs) -> dict[str, Any]:
    src = s.store.source(a.source_id)
    if not src:
        raise DarwinError("not_found", f"Discovery {a.source_id} does not exist.")
    pid = s.store.upsert_proposal(key=f"{src['key']}->{a.target}", source_id=a.source_id, target=a.target, state=a.state,
                                  origin="agent", reason=a.reason, capability_key=a.capability, agora_space=a.agora_space,
                                  agora_task=a.agora_task, by="agent")
    return {"proposal": s.store.one("SELECT * FROM proposals WHERE id=?", (pid,)), "history": s.store.history_of("proposals", pid)}


def _set_state(s: Services, a: SetStateArgs) -> dict[str, Any]:
    allowed = {("proposals", "state"): PROPOSAL_STATES, ("deliveries", "implementation"): IMPLEMENTATION_STATES,
               ("deliveries", "verification"): VERIFICATION_STATES}
    if (a.entity, a.field) not in allowed:
        raise DarwinError("invalid", f"{a.entity}.{a.field} is not a state.", "proposals.state, deliveries.implementation or deliveries.verification.")
    if a.value not in allowed[(a.entity, a.field)]:
        raise DarwinError("invalid", f"{a.value} is not a valid {a.field}.", ", ".join(allowed[(a.entity, a.field)]))
    if a.entity == "deliveries" and a.field == "implementation" and a.value == "integrada":
        row = s.store.one("SELECT commit_sha, agora_task FROM deliveries WHERE id=?", (a.id,))
        if row and not (row["commit_sha"] or row["agora_task"]):
            raise DarwinError("invalid", "«integrada» needs a commit or an Ágora task on the delivery.", "Record the evidence first.")
    try:
        changed = s.store.set_state(a.entity, a.id, a.field, a.value, by=a.by, note=a.note)
    except KeyError as exc:
        raise DarwinError("not_found", str(exc)) from exc
    return {"changed": changed, "history": s.store.history_of(a.entity, a.id)}


def _tree(s: Services, a: TreeArgs) -> dict[str, Any]:
    t = tree.subtree(s.store, a.root, a.depth, include_tools=a.tools)
    if t is None:
        if not s.store.counts()["capabilities"]:
            s.refresh_tree()
            t = tree.subtree(s.store, a.root, a.depth, include_tools=a.tools)
        if t is None:
            raise DarwinError("not_found", f"No node {a.root}.", "Start from 'faustus' or 'hoardhub'.")
    return {"tree": t, "path": tree.path_of(s.store, a.root), "refreshed_at": s.store.get_meta("tree_refreshed_at")}


def _gap(s: Services, a: GapArgs) -> dict[str, Any]:
    gid = s.store.add_gap(title=a.title, detail=a.detail, target=a.target, capability_key=a.capability,
                          watch={"condition": a.watch} if a.watch else None)
    return s.store.one("SELECT * FROM gaps WHERE id=?", (gid,))


def _suit_save(s: Services, a: SuitSaveArgs) -> dict[str, Any]:
    return suits.save_suit(s.store, a.model_dump(exclude_unset=True), by="agent")


def _suit_import(s: Services, a: SuitEvalImportArgs) -> dict[str, Any]:
    payload = a.result
    if payload is None:
        if not a.path:
            raise DarwinError("invalid", "Give the evaluation as result or as path.")
        import json
        from pathlib import Path
        try:
            payload = json.loads(Path(a.path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DarwinError("invalid", f"Cannot read the evaluation file: {exc}") from exc
    return suits.import_evaluation(s.store, payload, slug=a.slug)


def _mark(s: Services, a: MarkArgs) -> dict[str, Any]:
    out = backing.mark(s.store, a.key, implemented=a.implemented, evidence=[e.model_dump() for e in a.evidence] if a.implemented else None,
                       note=a.note, by=a.by)
    out["gaps"] = reconcile.reconcile(s.store, by=a.by)
    return out


def _gaps(s: Services, a: Empty) -> dict[str, Any]:
    rec = reconcile.listing(s.store)
    flags = {g["id"]: g for g in rec["possibly_stale"]}
    gaps = s.store.q("SELECT * FROM gaps ORDER BY state, updated DESC")
    for g in gaps:
        if g["id"] in flags:
            f = flags[g["id"]]
            g["possibly_stale"] = {"capability_key": f["capability_key"], "capability_name": f["capability_name"], "evidence": f["evidence"],
                                   "reason": f["reason"]}
    return {"gaps": gaps, "open": rec["open"], "possibly_stale": rec["stale_count"]}


TOOLS: list[Tool] = [
    Tool("darwin_overview", _d("Overview: how many discoveries, proposals per state, deliveries, captures per channel, apps with most proposals, last imports."),
         Empty, ann(read_only=True), lambda s, a: query.overview(s.store)),
    Tool("darwin_find", _d("Search the discovery history with filters and order.", "Each result has its aggregate state, target apps, proposals and deliveries.",
                           "historial, buscar repo, radar, qué hay de"), FindArgs, ann(read_only=True), _find),
    Tool("darwin_source", _d("One discovery's genealogy: captures with provenance, proposals per app with history, deliveries with commits.",
                             synonyms="dónde acabó, qué pasó con, historia de"), SourceArgs, ann(read_only=True), _source),
    Tool("darwin_add", _d("Add a discovery (URL, owner/repo or text) or get the existing one with its states, so nobody analyses it twice.",
                          synonyms="apuntar, guardar repo, nuevo descubrimiento"), AddArgs, ann(idempotent=True), _add),
    Tool("darwin_propose", _d("Record (or update) a proposal: this discovery for this app, with reason and Ágora task."),
         ProposeArgs, ann(idempotent=True), _propose),
    Tool("darwin_set_state", _d("Change a proposal state or a delivery's implementation/verification, keeping the history."),
         SetStateArgs, ann(idempotent=True), _set_state),
    Tool("darwin_tree", _d("The capability tree from a node: Faustus > Hub > Hoards > modules > capabilities > tools, with evidence and state.",
                           synonyms="árbol, mapa de capacidades, qué hace cada hoard"), TreeArgs, ann(read_only=True), _tree),
    Tool("darwin_capability_find", _d("Which apps already do something, with the matching capabilities/tools and their path in the tree.",
                                      synonyms="quién hace, dónde hacemos, ya tenemos"), CapFindArgs, ann(read_only=True),
         lambda s, a: tree.find(s.store, a.query, a.limit, a.tools)),
    Tool("darwin_tree_refresh", _d("Rebuild the capability tree now from the hub, Faustus's tool catalogue and the manifests."),
         Empty, ann(idempotent=True), lambda s, a: s.refresh_tree(), timeout_s=120),
    Tool("darwin_gaps", _d("Gaps: things Luis wants that no app does yet, with the ones the tree now answers flagged possibly_stale.",
                           "«open» counts only gaps not flagged; a flagged gap shows the capability and its evidence."), Empty, ann(read_only=True), _gaps),
    Tool("darwin_gaps_reconcile", _d("Flag gaps that a capability marked implemented with evidence now answers (possibly stale); list them.",
                                     "Never closes a gap by itself. confirm_ids resolves gaps a person checked; dismiss_ids keeps a flagged gap open.",
                                     "carencias obsoletas, reconciliar, ya está hecho, conciliar carencias"),
         ReconcileArgs, ann(idempotent=True), lambda s, a: reconcile.reconcile(s.store, confirm_ids=a.confirm_ids, dismiss_ids=a.dismiss_ids, by=a.by)),
    Tool("darwin_capability_mark", _d("Mark a capability node as implemented with evidence (commit, test or QA file); refused without evidence.",
                                      "A capability name alone proves nothing. Evidence is what lets suits read «backed» and gaps read «possibly stale».",
                                      "marcar implementada, aportar prueba, respaldo de una capacidad"), MarkArgs, ann(idempotent=True), _mark),
    Tool("darwin_suits", _d("What engagements Darwin can solve: suits with status proposed / partial / backed / evaluated.",
                            "A suit is a reusable work configuration for a kind of job. backed needs every required operation to exist in the tree with evidence.",
                            "trajes, qué encargos sabes resolver, biblioteca de trajes, suits"), SuitsArgs, ann(read_only=True),
         lambda s, a: suits.list_suits(s.store, a.status)),
    Tool("darwin_suit_get", _d("One suit in full: objective, inputs, concepts, operations with their state, views, acceptance, recipe, judgement points.",
                               "Each operation says backed, unproven (exists but no evidence) or missing; an evaluation shows its arms and excluded cases.",
                               "ver un traje, detalle del traje"), SuitRef, ann(read_only=True), lambda s, a: suits.get_suit(s.store, a.slug)),
    Tool("darwin_suit_save", _d("Create or update a suit by slug; only the fields given change.",
                                "Operations reference capability nodes by key; an operation without key is declared missing.", "crear traje, editar traje, guardar traje"),
         SuitSaveArgs, ann(idempotent=True), _suit_save),
    Tool("darwin_suit_delete", _d("Delete a suit and its imported evaluations."), SuitRef, ann(), lambda s, a: suits.delete_suit(s.store, a.slug)),
    Tool("darwin_suits_seed", _d("Insert the six suits of research proposal 36 that are not in the library yet (never overwrites)."),
         Empty, ann(idempotent=True), lambda s, a: suit_seeds.seed(s.store)),
    Tool("darwin_suit_import_eval", _d("Import a suit evaluation exported by Pygmalion's Hoard; the suit becomes evaluated.",
                                       "Needs at least one scored case; cases used to build the improvement arrive excluded. The backing at import time is kept.",
                                       "importar evaluación de un traje, resultados de Pygmalion"), SuitEvalImportArgs, ann(idempotent=True), _suit_import),
    Tool("darwin_gap_add", _d("Record a gap (something wanted that nothing does), optionally with the condition that would make it solvable."),
         GapArgs, ann(), _gap),
    Tool("darwin_changes_since", _d("What changed since a moment: new discoveries and captures, state changes, deliveries.",
                                    synonyms="qué hay de nuevo, desde la última vez"), SinceArgs, ann(read_only=True),
         lambda s, a: query.changes_since(s.store, a.since if a.since is not None else time.time() - 7 * 86400, a.limit)),
    Tool("darwin_inbox", _d("Captures not linked to any discovery yet (a chat note, a screenshot without a URL): kept to be enriched.",
                             synonyms="bandeja, sin clasificar"), InboxArgs, ann(read_only=True),
         lambda s, a: query.inbox(s.store, channel=a.channel, limit=a.limit, offset=a.offset)),
    Tool("darwin_ingest", _d("Store captures from another app (Links, Talos OCR, a chat) idempotently by capture_key and link their URLs/repos."),
         IngestArgs, ann(idempotent=True), lambda s, a: s.ingest(a.records, a.channel)),
    Tool("darwin_verify_deliveries", _d("Check every delivery's commit against the main branch of its local repository (no fetch, no checkout).",
                                        "A commit in main is code evidence, not a functional test. Old repository names go through the alias map; "
                                        "a commit missing after a history rewrite is matched by patch-id or subject+author date (equivalent_of), "
                                        "or by the commit the Ágora task says reached main; an app folded into another without its history "
                                        "reads «imported». Summary keys: integrated, integrated:<via>, imported, not_in_main, unknown:<reason>.",
                                        "comprobar entregas, commits en main, historia reescrita, equivalente"),
         Empty, ann(idempotent=True), lambda s, a: s.verify_deliveries(), timeout_s=600),
    Tool("darwin_repo_aliases", _d("Where each repository name deliveries use lives today: built-in and Luis's aliases, the folder of apps "
                                   "folded into others, and the names nothing resolves yet.",
                                   synonyms="mapa de repositorios, alias de repos, repos renombrados, apps fusionadas"),
         Empty, ann(read_only=True), lambda s, a: s.repo_aliases()),
    Tool("darwin_repo_alias_set", _d("Save (or remove) an alias: an old repository name → today's repository (and subfolder of a folded app).",
                                     "Saved in settings repo_aliases; it wins over the built-in alias for the same name. Run darwin_verify_deliveries after.",
                                     "mapear repositorio, añadir alias, repo fusionado"),
         RepoAliasArgs, ann(idempotent=True),
         lambda s, a: s.set_repo_alias(a.name, repo=a.repo, path=a.path, subdir=a.subdir, search=a.search, remove=a.remove)),
    Tool("darwin_whatsapp_chats", _d("WhatsApp chats Faustus's bridge knows (to pick the Gittrend chat's exact JID)."),
         ChatsArgs, ann(read_only=True), lambda s, a: {"chats": s.whatsapp_chats(a.query)}),
    Tool("darwin_sync_whatsapp", _d("Read the chosen WhatsApp chat through Faustus's bridge, page by page, without repeating what is stored.",
                                    "Read only: it never sends or marks anything as read.", "gittrend, sincronizar whatsapp"),
         SyncArgs, ann(idempotent=True), lambda s, a: s.sync_whatsapp(chat=a.chat, max_pages=a.max_pages), timeout_s=600),
    Tool("darwin_ask", _d("Answer a question in plain words from the capability tree, the discoveries and the gaps, citing them.",
                          "Retrieval runs locally; the answer is written by the family's local model. Without a model the material is returned.",
                          "pregunta, preguntar, qué tenemos, quién hace"),
         AskArgs, ann(read_only=True), lambda s, a: s.ask(a.question), timeout_s=180),
    Tool("darwin_import_links", _d("Bring in what Luis saved in Links for Darwin: links tagged darwin and every GitHub repository (idempotent).",
                                   "Words of a title never become a guessed owner/name.", "links, enlaces guardados, importar"),
         Empty, ann(idempotent=True), lambda s, a: s.import_links(), timeout_s=120),
    Tool("darwin_brain_export", _d("Write Darwin into Faustus's Brain as linked Markdown notes (Notes/Darwin: index, one note per app, one per live discovery).",
                                   "Only Darwin's own notes are overwritten or removed; runs every few hours on its own.", "cerebro, brain, exportar, notas"),
         Empty, ann(idempotent=True), lambda s, a: s.brain_export(), timeout_s=300),
    Tool("darwin_accounts", _d("Which sites Links holds a signed-in session for (X, Instagram, Threads, TikTok, Reddit…), to read posts.",
                               "No cookie values are ever returned.", "cuentas, sesiones, conectar instagram, conectar x"),
         Empty, ann(read_only=True), lambda s, a: s.accounts(), timeout_s=30),
    Tool("darwin_account_login", _d("Open Links' sign-in window for a site on Luis's computer; he signs in himself and the session is kept.",
                                    "Never ask for or type a password.", "conectar cuenta, iniciar sesión"),
         LoginArgs, ann(), lambda s, a: s.account_login(a.site, finish=a.finish, cancel=a.cancel), timeout_s=60),
    Tool("darwin_read_posts", _d("Read the social posts behind discoveries (X, Instagram, Threads…) with the signed-in sessions and link the repositories and links inside.",
                                 "Each post is read once; a login wall stops the run and names the site.", "leer tuits, leer posts, de qué repo habla"),
         PostsArgs, ann(idempotent=True), lambda s, a: s.read_posts(limit=a.limit), timeout_s=900),
    Tool("darwin_discuss", _d("Open (or show) the Ágora thread that debates one proposal, with the discovery's genealogy; an optional note is added.",
                              "One thread per proposal, kept on it; Darwin writes as the agent darwin.", "debatir, discutir, ágora"),
         DiscussArgs, ann(), lambda s, a: s.discuss(a.proposal_id, a.note), timeout_s=60),
    Tool("darwin_triage", _d("Suggest an app for discoveries nobody proposed yet: a pending proposal with origin agent, or a note that it is noise.",
                             "The family's local model picks from the real app catalogue; Luis's decisions are never overwritten.",
                             "repartir, clasificar, triaje, proponer apps"),
         TriageArgs, ann(idempotent=True), lambda s, a: s.triage(channel=a.channel, limit=a.limit), timeout_s=900),
    Tool("darwin_read_screenshots", _d("Read the unread screenshots in the inbox with the family's OCR and link the repositories and links they show.",
                                       "URLs are taken as read; bare owner/name only when GitHub confirms the repository. An image is read once.",
                                       "ocr, capturas, fotos, pantallazos"),
         OcrArgs, ann(idempotent=True), lambda s, a: s.ocr_inbox(limit=a.limit), timeout_s=900),
    Tool("darwin_coverage", _d("Does the family already do this? A discovery or a free text against the capability tree: covered, partial or gap, with the matching apps and nodes.",
                               "covered needs half of the text's ideas (three or more) in one app's capabilities or tools, with live, tested or backed nodes. "
                               "It explains, it never blocks.", "ya lo tenemos, cobertura, aptitud, encaja, cubre"),
         CoverageArgs, ann(read_only=True), _coverage),
    Tool("darwin_radar_plan", _d("The gap-driven radar: open gaps ranked by how much a search would help, each with its GitHub and web queries, the "
                                 "discoveries Darwin already holds that may answer it and whether the tree may already cover it.",
                                 "notify is false when nothing changed since the previous plan: a scheduled radar stays quiet then. Then run the "
                                 "searches (or darwin_radar_run) and record findings with darwin_add.", "radar, qué buscar, plan del radar, carencias"),
         RadarPlanArgs, ann(idempotent=True), lambda s, a: s.radar_plan(limit=a.limit, remember=a.remember), timeout_s=150),
    Tool("darwin_radar_run", _d("Search GitHub for the plan's first gaps and report each repository as already known or new; add=true registers the new ones.",
                                "Uses GitHub's public anonymous search (ten searches a minute). A failed search is reported and the rest go on.",
                                "buscar repos para carencias, lanzar radar"),
         RadarRunArgs, ann(idempotent=True), lambda s, a: s.radar_run(top=a.top, per_gap=a.per_gap, add=a.add, gap_ids=a.gap_ids or None),
         timeout_s=240),
    Tool("darwin_watch_add", _d("Keep a question («avísame cuando…»): Darwin asks it again every few hours and tells Luis only when the answer grows.",
                                "The first check is the baseline; later ones report new discoveries, state changes and apps.",
                                "avísame cuando, pregunta guardada, vigilar"), WatchAddArgs, ann(),
         lambda s, a: watches.add(s.store, a.question, note=a.note, target=a.target)),
    Tool("darwin_watches", _d("Saved questions with their last news."), Empty, ann(read_only=True), lambda s, a: watches.listing(s.store)),
    Tool("darwin_watches_check", _d("Ask every saved question again now; notify is true when one has news (a family notification is sent)."),
         Empty, ann(idempotent=True), lambda s, a: s.check_watches(), timeout_s=180),
    Tool("darwin_watch_update", _d("Pause, resume or delete a saved question, or mark its news as read."), WatchUpdateArgs, ann(), _watch_update),
    Tool("darwin_proposals", _d("Proposals (a discovery for an app) filtered by state, app, origin or words, newest change first, with counts per state.",
                                synonyms="propuestas, qué se propuso, pendientes de decidir"), ProposalsArgs, ann(read_only=True),
         lambda s, a: views.proposals(s.store, state=a.state, target=a.target, origin=a.origin, query_text=a.query, limit=a.limit, offset=a.offset)),
    Tool("darwin_saved_filters", _d("List, save or delete named filters of the discovery history; darwin_find applies one with saved=<name>.",
                                    synonyms="filtros guardados, vistas guardadas"), FiltersArgs, ann(idempotent=True), _filters),
    Tool("darwin_panel", _d("What Darwin knows about one app (or the whole family): open discoveries worth a look, proposals by state, gaps, recent "
                            "changes; the family view adds the radar's next searches. Faustus's project panel shows it.",
                            "Resolves the app from its id, an Ágora space or a Faustus project name; research/ecosystem = the family.",
                            "resumen de una app, panel, qué hay para este hoard"), PanelArgs, ann(read_only=True),
         lambda s, a: views.panel(s.store, app=a.app, space=a.space, project=a.project, limit=a.limit), timeout_s=120),
    Tool("darwin_import_legacy", _d("Import (idempotently) the radar Markdown files, the tracker, the guide and the Ágora tasks that cite the radar."),
         ImportArgs, ann(idempotent=True), lambda s, a: s.import_legacy(**a.model_dump()), timeout_s=300),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tool_catalog() -> list[dict[str, Any]]:
    return _catalog(TOOLS)


def call_tool(svc: Services, name: str, arguments: Optional[dict[str, Any]], caller: str = "agent") -> Any:
    return _call_tool(TOOLS_BY_NAME, svc, name, arguments)
