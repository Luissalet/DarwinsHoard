"""Reading the store: the filterable history, one source's genealogy, the per-target view and the overview."""

from __future__ import annotations

import time
from typing import Any, Optional

from .canon import canonical_url, repo_key, source_key
from .store import Store

ORDERS = {
    "recent": "s.last_seen DESC, s.id DESC",
    "oldest": "s.first_seen ASC, s.id ASC",
    "radar": "COALESCE(s.legacy_radar_no, 999999) ASC, s.id ASC",
    "radar_desc": "COALESCE(s.legacy_radar_no, -1) DESC, s.id DESC",
    "captures": "s.captures DESC, s.last_seen DESC",
    "title": "LOWER(s.title) ASC",
}

#: Aggregated state of a source, computed from its proposals and deliveries, most advanced first. Shown as such
#: ("agregado"), never stored: the axes stay separate underneath.
AGGREGATE_ORDER = ["integrada", "parcial", "aceptada", "investigando", "debatida", "pendiente", "aplazada", "cubierta", "descartada", "sin_propuesta"]


def _aggregate(proposals: list[dict[str, Any]], implementations: list[str]) -> str:
    """A proposal without a target (a radar line that named no app) only counts while no app-specific decision exists."""
    targeted = [p for p in proposals if p.get("target")]
    proposal_states = [p["state"] for p in (targeted or proposals)]
    if "integrada" in implementations:
        return "integrada"
    if "parcial" in implementations:
        return "parcial"
    for state in AGGREGATE_ORDER[2:-1]:
        if state in proposal_states:
            return state
    return "sin_propuesta"


def find(store: Store, *, query: str = "", state: str = "", target: str = "", channel: str = "", kind: str = "",
         pinned: Optional[bool] = None, radar_from: Optional[int] = None, radar_to: Optional[int] = None,
         order: str = "recent", limit: int = 50, offset: int = 0) -> dict[str, Any]:
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
                             "OR s.id IN (SELECT source_id FROM captures WHERE LOWER(text) LIKE ?))")
                args += [like, like, like, like]
    if target:
        where.append("(s.id IN (SELECT source_id FROM proposals WHERE target=?) OR s.id IN (SELECT source_id FROM deliveries WHERE target=?))")
        args += [target, target]
    if channel:
        where.append("s.id IN (SELECT source_id FROM captures WHERE channel=?)")
        args.append(channel)
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
    props = _by_source(store, "SELECT source_id, id, target, state, reason, origin, agora_space, agora_task FROM proposals", ids)
    dels = _by_source(store, "SELECT source_id, id, target, implementation, verification, commit_sha, relation FROM deliveries", ids)
    items = []
    for r in rows:
        p, d = props.get(r["id"], []), dels.get(r["id"], [])
        agg = _aggregate(p, [x["implementation"] for x in d])
        if state and state != agg and state not in {x["state"] for x in p} and state not in {x["implementation"] for x in d}:
            continue
        items.append(_summary(r, p, d, agg))
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
    return {"id": r["id"], "key": r["key"], "kind": r["kind"], "title": r["title"], "url": r["url"], "repo": r["repo"],
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
    agg = _aggregate(props, [d["implementation"] for d in dels])
    return {"source": src, "aliases": aliases, "state": agg, "captures": caps, "ideas": ideas, "proposals": props, "deliveries": dels}


def overview(store: Store) -> dict[str, Any]:
    counts = store.counts()
    by_state = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) AS n FROM proposals WHERE target IS NOT NULL GROUP BY state")}
    untargeted = store.one("SELECT COUNT(*) AS n FROM proposals WHERE target IS NULL")["n"]
    by_impl = {r["implementation"]: r["n"] for r in store.q("SELECT implementation, COUNT(*) AS n FROM deliveries GROUP BY implementation")}
    by_verif = {r["verification"]: r["n"] for r in store.q("SELECT verification, COUNT(*) AS n FROM deliveries GROUP BY verification")}
    by_channel = {r["channel"]: r["n"] for r in store.q("SELECT channel, COUNT(*) AS n FROM captures GROUP BY channel")}
    targets = store.q("SELECT target, COUNT(*) AS proposals, SUM(state IN ('aceptada','investigando')) AS active, "
                      "SUM(state='pendiente') AS pending FROM proposals WHERE target IS NOT NULL GROUP BY target ORDER BY proposals DESC")
    imports = store.q("SELECT name, file, sha256, at, counts FROM imports ORDER BY at DESC LIMIT 12")
    week = time.time() - 7 * 86400
    recent = store.one("SELECT COUNT(*) AS n FROM captures WHERE created>=? AND channel NOT IN ('radar','radar-ideas','tracker','guide','agora')",
                       (week,))["n"]
    radar = store.one("SELECT COUNT(DISTINCT legacy_radar_no) AS n, MAX(legacy_radar_no) AS max FROM sources WHERE legacy_radar_no IS NOT NULL")
    agg: dict[str, int] = {}
    ids = [r["id"] for r in store.q("SELECT id FROM sources")]
    props = _by_source(store, "SELECT source_id, target, state FROM proposals", ids)
    dels = _by_source(store, "SELECT source_id, implementation FROM deliveries", ids)
    for sid in ids:
        a = _aggregate(props.get(sid, []), [d["implementation"] for d in dels.get(sid, [])])
        agg[a] = agg.get(a, 0) + 1
    return {"counts": counts, "sources_by_state": agg, "proposals_untargeted": untargeted,
            "radar_missing": store.get_meta("radar_missing", []), "proposals_by_state": by_state, "deliveries_by_implementation": by_impl,
            "deliveries_by_verification": by_verif, "captures_by_channel": by_channel, "targets": targets,
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
