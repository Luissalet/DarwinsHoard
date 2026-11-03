"""Reading the store: the filterable history, one source's genealogy, the per-target view and the overview."""

from __future__ import annotations

import time
from typing import Any, Optional

from .canon import canonical_url, repo_key, source_key
from .store import OPEN_GAP_SQL, Store

ORDERS = {
    "recent": "s.last_seen DESC, s.id DESC",
    "oldest": "s.first_seen ASC, s.id ASC",
    "radar": "COALESCE(s.legacy_radar_no, 999999) ASC, s.id ASC",
    "radar_desc": "COALESCE(s.legacy_radar_no, -1) DESC, s.id DESC",
    "captures": "s.captures DESC, s.last_seen DESC",
    "title": "LOWER(s.title) ASC",
    "fitness": "s.last_seen DESC",  # re-sorted by score below
}

#: Aggregated state of a source, computed from its proposals and deliveries, most advanced first. Shown as such
#: ("agregado"), never stored: the axes stay separate underneath.
AGGREGATE_ORDER = ["integrada", "mixta", "parcial", "aceptada", "investigando", "debatida", "pendiente", "aplazada", "cubierta", "descartada", "sin_propuesta"]


CLOSED_PROPOSAL_STATES = ("descartada", "cubierta")


def _delivers(d: dict[str, Any], p: dict[str, Any], open_in_target: int) -> bool:
    """Whether delivery ``d`` fulfils proposal ``p``. The finest identity both carry decides:

    * a delivery linked to a proposal (``proposal_id``) fulfils that proposal only;
    * otherwise a proposal without a target (a radar line that named no app) is fulfilled by any delivery;
    * otherwise the target must match, and when both name a capability it must be the same one;
    * a delivery that names no capability fulfils a capability-specific proposal only when that proposal is the only open
      one for its target (two open capabilities of one app are never closed by one unnamed delivery)."""
    if d.get("proposal_id") is not None and p.get("id") is not None:
        return d["proposal_id"] == p["id"]
    if not p.get("target"):
        return True
    if d.get("target") != p.get("target"):
        return False
    d_cap, p_cap = d.get("capability_key") or "", p.get("capability_key") or ""
    if d_cap and p_cap:
        return d_cap == p_cap
    if p_cap and not d_cap:
        return open_in_target <= 1
    return True


def _aggregate(proposals: list[dict[str, Any]], deliveries: list[Any]) -> str:
    """Aggregate state of a source, for display only.

    The unit is the proposal (an app, or an app's capability), not the app: two proposals for two capabilities of the
    same app are two units, and an integrated delivery closes only the units it fulfils (see :func:`_delivers`).

    * A proposal without a target only counts while no app-specific one exists.
    * ``integrada`` only when every unit still meant to happen (not discarded or covered) has an integrated delivery;
      ``mixta`` when some do and others are pending or partial, so one delivery never makes the whole source look done.
    * ``parcial`` when nothing is integrated and some delivery is partial."""
    dels = [d if isinstance(d, dict) else {"implementation": d, "target": None} for d in deliveries]
    targeted = [p for p in proposals if p.get("target")]
    units = targeted or list(proposals)
    proposal_states = [p["state"] for p in units]
    open_units = [p for p in units if p["state"] not in CLOSED_PROPOSAL_STATES]
    open_per_target: dict[Any, int] = {}
    for p in open_units:
        open_per_target[p.get("target")] = open_per_target.get(p.get("target"), 0) + 1
    integrated = [d for d in dels if d.get("implementation") == "integrada"]
    partial = [d for d in dels if d.get("implementation") == "parcial"]

    def fulfils(d: dict[str, Any], p: dict[str, Any]) -> bool:
        return _delivers(d, p, open_per_target.get(p.get("target"), 0))

    done = [p for p in open_units if any(fulfils(d, p) for d in integrated)]
    # an integrated delivery that fulfils no open proposal (an app nobody proposed, or one later discarded) still counts
    # as something done: with open proposals left the source is «mixta», with none it is «integrada»
    stray_done = [d for d in integrated if not any(fulfils(d, p) for p in open_units)]
    if done or stray_done:
        return "mixta" if len(done) < len(open_units) else "integrada"
    if partial:
        return "parcial"
    for state in AGGREGATE_ORDER[3:-1]:
        if state in proposal_states:
            return state
    return "sin_propuesta"


def proof_of(deliveries: list[dict[str, Any]]) -> str:
    """How an «integrada» is backed: ``en_main`` (a commit proven in the main branch), ``documentos`` (only declared),
    ``fuera_de_main`` (the declared commit is missing or not in main) or ``""`` when nothing is integrated."""
    states = []
    for d in deliveries:
        if d.get("implementation") != "integrada":
            continue
        ev = d.get("evidence") if isinstance(d.get("evidence"), dict) else {}
        states.append(((ev or {}).get("commit_ancestry") or {}).get("status") or "")
    if not states:
        return ""
    if "integrated" in states:
        return "en_main"
    if any(s in ("not_in_main",) for s in states) or any(
            ((d.get("evidence") or {}).get("commit_ancestry") or {}).get("reason") == "commit_not_found" for d in deliveries if isinstance(d.get("evidence"), dict)):
        return "fuera_de_main"
    return "documentos"


def find(store: Store, *, query: str = "", state: str = "", target: str = "", channel: str = "", kind: str = "",
         pinned: Optional[bool] = None, radar_from: Optional[int] = None, radar_to: Optional[int] = None,
         order: str = "recent", limit: int = 50, offset: int = 0, with_fitness: bool = False) -> dict[str, Any]:
    """Sources with their proposals summarised. ``state`` filters on the aggregate or on any proposal state;
    ``target`` on any proposal or delivery target; ``channel`` on any capture channel."""
    where, args = ["1=1"], []
    if query:
        q = query.strip()
        if q.lstrip("#").isdigit():
            n = int(q.lstrip("#"))
            where.append("(s.legacy_radar_no=? OR s.id IN (SELECT source_id FROM captures WHERE json_extract(provenance, '$.radar_no')=?))")
            args += [n, n]
            q = ""
        key = (repo_key(q) or (("url:" + canonical_url(q)) if q.startswith("http") else "")) if q else ""
        if key:
            where.append("(s.key=? OR s.id IN (SELECT source_id FROM source_aliases WHERE alias=?))")
            args += [key, key]
        elif q:
            for word in q.lower().split()[:8]:
                like = f"%{word}%"
                where.append("(LOWER(COALESCE(s.title,'')) LIKE ? OR LOWER(COALESCE(s.repo,'')) LIKE ? OR LOWER(COALESCE(s.summary,'')) LIKE ? "
                             "OR s.id IN (SELECT source_id FROM captures WHERE LOWER(text) LIKE ?) "
                             "OR s.id IN (SELECT cs.source_id FROM capture_sources cs JOIN captures c ON c.id=cs.capture_id WHERE LOWER(c.text) LIKE ?))")
                args += [like, like, like, like, like]
    if target:
        where.append("(s.id IN (SELECT source_id FROM proposals WHERE target=?) OR s.id IN (SELECT source_id FROM deliveries WHERE target=?))")
        args += [target, target]
    if channel:
        where.append("(s.id IN (SELECT source_id FROM captures WHERE channel=?) OR "
                     "s.id IN (SELECT cs.source_id FROM capture_sources cs JOIN captures c ON c.id=cs.capture_id WHERE c.channel=?))")
        args += [channel, channel]
    if kind:
        where.append("s.kind=?")
        args.append(kind)
    if pinned is not None:
        where.append("(json_extract(s.meta, '$.pinned') IS " + ("1)" if pinned else "NULL OR json_extract(s.meta, '$.pinned')=0)"))
    if radar_from is not None:
        where.append("s.legacy_radar_no>=?")
        args.append(radar_from)
    if radar_to is not None:
        where.append("s.legacy_radar_no<=?")
        args.append(radar_to)
    rows = store.q(f"SELECT s.* FROM sources s WHERE {' AND '.join(where)} ORDER BY {ORDERS.get(order, ORDERS['recent'])}", args)
    ids = [r["id"] for r in rows]
    props = _by_source(store, "SELECT source_id, id, target, capability_key, state, reason, origin, agora_space, agora_task FROM proposals", ids)
    dels = _by_source(store, "SELECT source_id, id, proposal_id, target, capability_key, implementation, verification, commit_sha, relation, "
                             "evidence FROM deliveries", ids)
    items = []
    for r in rows:
        p, d = props.get(r["id"], []), dels.get(r["id"], [])
        agg = _aggregate(p, d)
        if state and state != agg and state not in {x["state"] for x in p} and state not in {x["implementation"] for x in d}:
            continue
        items.append(_summary(r, p, d, agg))
    if order == "fitness" or with_fitness:
        from . import fitness as fit
        gaps = fit.gap_terms(store)
        texts = fit.texts_by_source(store, [i["id"] for i in items])
        by_id = {r["id"]: r for r in rows}
        for it in items:
            f = fit.score(by_id[it["id"]], it["state"], text=texts.get(it["id"], ""), gaps=gaps)
            it["fitness"], it["fitness_reasons"] = f["score"], f["reasons"]
        if order == "fitness":
            items.sort(key=lambda i: -i["fitness"])
    total = len(items)
    return {"total": total, "offset": offset, "limit": limit, "items": items[offset:offset + limit]}


def _by_source(store: Store, sql: str, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        if not part:
            continue
        for row in store.q(f"{sql} WHERE source_id IN ({','.join('?' * len(part))})", part):
            out.setdefault(row.pop("source_id"), []).append(row)
    return out


def _summary(r: dict[str, Any], props: list[dict[str, Any]], dels: list[dict[str, Any]], agg: str) -> dict[str, Any]:
    targets = sorted({x["target"] for x in props + dels if x.get("target")})
    proof = proof_of(dels)
    for x in dels:
        x.pop("evidence", None)
    return {"proof": proof, "id": r["id"], "key": r["key"], "kind": r["kind"], "title": r["title"], "url": r["url"], "repo": r["repo"],
            "radar_no": r["legacy_radar_no"], "stars": r["stars"], "summary": (r["summary"] or "")[:280],
            "pinned": bool((r.get("meta") or {}).get("pinned")) if isinstance(r.get("meta"), dict) else False,
            "first_seen": r["first_seen"], "last_seen": r["last_seen"], "captures": r["captures"], "state": agg,
            "targets": targets, "proposals": props, "deliveries": dels}


def genealogy(store: Store, *, source_id: Optional[int] = None, key: str = "", radar_no: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Everything known about one source: captures (with provenance), ideas, proposals with their history, deliveries."""
    src = None
    if source_id:
        src = store.source(source_id)
    elif radar_no is not None:
        src = store.one("SELECT * FROM sources WHERE legacy_radar_no=? ORDER BY id LIMIT 1", (radar_no,))
    elif key:
        k = key if ":" in key and not key.startswith("http") else (repo_key(key) or source_key(url=key) if key.startswith("http") or "/" in key else key)
        src = store.source_by_key(k)
    if not src:
        return None
    sid = src["id"]
    props = store.q("SELECT * FROM proposals WHERE source_id=? ORDER BY target", (sid,))
    for p in props:
        p["history"] = store.history_of("proposals", p["id"])
    dels = store.q("SELECT * FROM deliveries WHERE source_id=? ORDER BY target, created", (sid,))
    for d in dels:
        d["history"] = store.history_of("deliveries", d["id"])
    caps = store.q("SELECT c.* FROM captures c WHERE c.source_id=? OR c.id IN (SELECT capture_id FROM capture_sources WHERE source_id=?) "
                   "ORDER BY c.at", (sid, sid))
    aliases = [r["alias"] for r in store.q("SELECT alias FROM source_aliases WHERE source_id=?", (sid,))]
    ideas = store.q("SELECT * FROM ideas WHERE source_id=?", (sid,))
    agg = _aggregate(props, dels)
    from . import fitness as fit
    fitness = fit.score(src, agg, text=fit.texts_by_source(store, [sid]).get(sid, ""), gaps=fit.gap_terms(store))
    return {"proof": proof_of(dels), "source": src, "aliases": aliases, "state": agg, "captures": caps, "ideas": ideas, "proposals": props,
            "deliveries": dels, "fitness": fitness}


def overview(store: Store) -> dict[str, Any]:
    counts = store.counts()
    counts["gaps_open"] = store.one("SELECT COUNT(*) AS n FROM gaps WHERE " + OPEN_GAP_SQL)["n"]
    counts["gaps_possibly_stale"] = store.one("SELECT COUNT(*) AS n FROM gap_flags f JOIN gaps g ON g.id=f.gap_id WHERE f.status='possibly_stale' AND g.state='abierta'")["n"]
    counts["suits"] = store.one("SELECT COUNT(*) AS n FROM suits")["n"]
    by_state = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) AS n FROM proposals WHERE target IS NOT NULL GROUP BY state")}
    untargeted = store.one("SELECT COUNT(*) AS n FROM proposals WHERE target IS NULL")["n"]
    by_impl = {r["implementation"]: r["n"] for r in store.q("SELECT implementation, COUNT(*) AS n FROM deliveries GROUP BY implementation")}
    by_verif = {r["verification"]: r["n"] for r in store.q("SELECT verification, COUNT(*) AS n FROM deliveries GROUP BY verification")}
    by_channel = {r["channel"]: r["n"] for r in store.q("SELECT channel, COUNT(*) AS n FROM captures GROUP BY channel")}
    by_ancestry = {}
    for r in store.q("SELECT COALESCE(json_extract(evidence, '$.commit_ancestry.status'), 'sin_comprobar') AS st, "
                     "json_extract(evidence, '$.commit_ancestry.reason') AS why, COUNT(*) AS n FROM deliveries GROUP BY st, why"):
        key = {"integrated": "en_main", "not_in_main": "fuera_de_main"}.get(r["st"]) or (
            "commit_no_encontrado" if r["why"] == "commit_not_found" else "sin_comprobar")
        by_ancestry[key] = by_ancestry.get(key, 0) + r["n"]
    targets = store.q("SELECT target, COUNT(*) AS proposals, SUM(state IN ('aceptada','investigando')) AS active, "
                      "SUM(state='pendiente') AS pending FROM proposals WHERE target IS NOT NULL GROUP BY target ORDER BY proposals DESC")
    imports = store.q("SELECT name, file, sha256, at, counts FROM imports ORDER BY at DESC LIMIT 12")
    week = time.time() - 7 * 86400
    recent = store.one("SELECT COUNT(*) AS n FROM captures WHERE created>=? AND channel NOT IN ('radar','radar-ideas','tracker','guide','agora')",
                       (week,))["n"]
    radar = store.one("SELECT COUNT(DISTINCT legacy_radar_no) AS n, MAX(legacy_radar_no) AS max FROM sources WHERE legacy_radar_no IS NOT NULL")
    agg: dict[str, int] = {}
    ids = [r["id"] for r in store.q("SELECT id FROM sources")]
    props = _by_source(store, "SELECT source_id, id, target, capability_key, state FROM proposals", ids)
    dels = _by_source(store, "SELECT source_id, proposal_id, target, capability_key, implementation FROM deliveries", ids)
    for sid in ids:
        a = _aggregate(props.get(sid, []), dels.get(sid, []))
        agg[a] = agg.get(a, 0) + 1
    return {"counts": counts, "sources_by_state": agg, "proposals_untargeted": untargeted,
            "radar_missing": store.get_meta("radar_missing", []), "proposals_by_state": by_state, "deliveries_by_implementation": by_impl,
            "deliveries_by_verification": by_verif, "deliveries_by_ancestry": by_ancestry,
            "deliveries_verified_at": store.get_meta("deliveries_verified_at"), "captures_by_channel": by_channel, "targets": targets,
            "imports": imports, "captures_last_7_days": recent, "radar": radar}


def changes_since(store: Store, since: float, limit: int = 200) -> dict[str, Any]:
    """What happened after ``since`` (epoch seconds): new sources and captures, state changes, new deliveries."""
    return {
        "since": since,
        "new_sources": store.q("SELECT id, key, title, kind, legacy_radar_no, created FROM sources WHERE created>=? ORDER BY created DESC LIMIT ?", (since, limit)),
        "new_captures": store.q("SELECT id, channel, source_id, at, substr(text,1,200) AS text FROM captures WHERE created>=? ORDER BY created DESC LIMIT ?", (since, limit)),
        "state_changes": store.q("SELECT * FROM history WHERE at>=? ORDER BY at DESC LIMIT ?", (since, limit)),
        "new_deliveries": store.q("SELECT id, source_id, target, commit_sha, implementation, verification, created FROM deliveries WHERE created>=? ORDER BY created DESC LIMIT ?", (since, limit)),
    }


def inbox(store: Store, *, channel: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Captures that no source is linked to yet: a chat note, a screenshot without a URL. Kept, never dropped."""
    where, args = ["c.source_id IS NULL", "NOT EXISTS (SELECT 1 FROM capture_sources cs WHERE cs.capture_id=c.id)"], []
    if channel:
        where.append("c.channel=?")
        args.append(channel)
    sql = f"FROM captures c WHERE {' AND '.join(where)}"
    total = store.one(f"SELECT COUNT(*) AS n {sql}", args)["n"]
    rows = store.q(f"SELECT c.* {sql} ORDER BY c.at DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    return {"total": total, "items": rows}
