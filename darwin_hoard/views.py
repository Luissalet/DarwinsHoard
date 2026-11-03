"""Read models for the full views: the proposals list, saved history filters and the per-app summary that Faustus's
project panel shows (``/panel``)."""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from . import query
from .store import OPEN_GAP_SQL, PROPOSAL_STATES, Store

FILTER_KEYS = ("query", "state", "target", "channel", "kind", "pinned", "order")
FAMILY_SPACES = {"research", "ecosystem", "familia", "family", "hoards", "darwin-family"}


def proposals(store: Store, *, state: str = "", target: str = "", origin: str = "", query_text: str = "",
              limit: int = 100, offset: int = 0) -> dict[str, Any]:
    where, args = ["1=1"], []
    if state:
        where.append("p.state=?")
        args.append(state)
    if target:
        where.append("p.target=?")
        args.append(target)
    if origin:
        where.append("p.origin LIKE ?")
        args.append(origin + "%")
    for word in query_text.lower().split()[:6]:
        like = f"%{word}%"
        where.append("(LOWER(COALESCE(s.title,'')) LIKE ? OR LOWER(COALESCE(s.repo,'')) LIKE ? OR LOWER(COALESCE(p.reason,'')) LIKE ?)")
        args += [like, like, like]
    sql_where = " AND ".join(where)
    total = store.one(f"SELECT COUNT(*) AS n FROM proposals p LEFT JOIN sources s ON s.id=p.source_id WHERE {sql_where}", args)["n"]
    rows = store.q("SELECT p.id, p.source_id, p.target, p.state, p.reason, p.origin, p.capability_key, p.agora_space, p.agora_task, "
                   "p.agora_thread, p.created, p.updated, s.title, s.repo, s.url, s.legacy_radar_no AS radar_no "
                   f"FROM proposals p LEFT JOIN sources s ON s.id=p.source_id WHERE {sql_where} "
                   "ORDER BY p.updated DESC, p.id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    counts = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) AS n FROM proposals GROUP BY state")}
    origins = {r["o"]: r["n"] for r in store.q("SELECT COALESCE(NULLIF(substr(origin, 1, instr(origin || ':', ':') - 1), ''), '?') AS o, "
                                               "COUNT(*) AS n FROM proposals GROUP BY o")}
    return {"total": total, "offset": offset, "limit": limit, "items": rows, "counts": {k: counts.get(k, 0) for k in PROPOSAL_STATES},
            "origins": origins}


# ---------------------------------------------------------------------- saved filters of the history

def saved_filters(store: Store) -> dict[str, dict[str, Any]]:
    return store.get_meta("saved_filters", {}) or {}


def save_filter(store: Store, name: str, spec: dict[str, Any]) -> dict[str, Any]:
    name = name.strip()[:60]
    if not name:
        raise ValueError("Give the filter a name.")
    clean = {k: spec[k] for k in FILTER_KEYS if k in spec and spec[k] not in (None, "")}
    if not clean:
        raise ValueError("The filter is empty: set at least a search, state, app, origin or order.")
    allf = saved_filters(store)
    allf[name] = {**clean, "saved": time.time()}
    store.set_meta("saved_filters", allf)
    return {"filters": allf}


def delete_filter(store: Store, name: str) -> dict[str, Any]:
    allf = saved_filters(store)
    if name not in allf:
        raise KeyError(f"No saved filter called {name}.")
    allf.pop(name)
    store.set_meta("saved_filters", allf)
    return {"filters": allf}


def apply_filter(store: Store, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Arguments of darwin_find with the saved filter underneath: what the caller sets explicitly wins."""
    spec = saved_filters(store).get(name)
    if spec is None:
        raise KeyError(f"No saved filter called {name}.")
    out = dict(args)
    for k in FILTER_KEYS:
        if k in spec and out.get(k) in (None, "", "recent" if k == "order" else None):
            out[k] = spec[k]
    return out


# ---------------------------------------------------------------------- the panel of a Faustus project

def _norm(value: str) -> str:
    v = re.sub(r"'s\b", "", str(value or "").lower())
    return re.sub(r"[^a-z0-9]", "", v.replace("hoard", ""))


def resolve_app(store: Store, *, app: str = "", space: str = "", project: str = "") -> Optional[dict[str, str]]:
    """The app a Faustus project (or Ágora space) is about, by id or name; None for the family-wide projects (Research)."""
    names = {r["app_id"]: r["name"] for r in store.q("SELECT app_id, name FROM capabilities WHERE level IN ('app','module','hub','root') "
                                                      "AND app_id IS NOT NULL")}
    for t in store.q("SELECT DISTINCT target FROM proposals WHERE target IS NOT NULL"):
        names.setdefault(t["target"], t["target"])
    wanted = [w for w in (app, space, project) if w]
    if not wanted or any(_norm(w) in FAMILY_SPACES or str(w).strip().lower() in FAMILY_SPACES for w in wanted):
        return None
    for w in wanted:
        if w in names:
            return {"app_id": w, "name": names[w]}
    by_norm = {}
    for aid, nm in names.items():
        for key in (_norm(aid), _norm(nm)):
            if key:
                by_norm.setdefault(key, aid)
    for w in wanted:
        aid = by_norm.get(_norm(w))
        if aid:
            return {"app_id": aid, "name": names[aid]}
    return None


def panel(store: Store, *, app: str = "", space: str = "", project: str = "", limit: int = 8) -> dict[str, Any]:
    """What Faustus's project panel shows: for one app, its open discoveries worth a look, its proposals by state, its gaps
    and the latest changes; for the family (Research), the same over every app plus the radar's next searches."""
    from . import radar, watches
    hit = resolve_app(store, app=app, space=space, project=project)
    target = hit["app_id"] if hit else ""
    found = query.find(store, target=target, order="fitness", limit=limit)
    open_items = [i for i in found["items"] if i.get("fitness")][:limit]
    if target:
        pcounts = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) AS n FROM proposals WHERE target=? GROUP BY state", (target,))}
        gaps = store.q("SELECT id, title, detail, created FROM gaps WHERE target=? AND " + OPEN_GAP_SQL + " ORDER BY created DESC", (target,))
        recent = store.q("SELECT p.id, p.state, p.updated, s.id AS source_id, s.title FROM proposals p LEFT JOIN sources s ON s.id=p.source_id "
                         "WHERE p.target=? ORDER BY p.updated DESC LIMIT 6", (target,))
    else:
        pcounts = {r["state"]: r["n"] for r in store.q("SELECT state, COUNT(*) AS n FROM proposals GROUP BY state")}
        gaps = store.q("SELECT id, title, detail, target, created FROM gaps WHERE " + OPEN_GAP_SQL + " ORDER BY created DESC LIMIT 12")
        recent = store.q("SELECT p.id, p.state, p.target, p.updated, s.id AS source_id, s.title FROM proposals p "
                         "LEFT JOIN sources s ON s.id=p.source_id ORDER BY p.updated DESC LIMIT 6")
    out: dict[str, Any] = {"app": hit, "scope": "app" if hit else "family", "asked": {"app": app, "space": space, "project": project},
                           "discoveries_total": found["total"], "top": open_items, "proposals_by_state": pcounts,
                           "gaps": gaps, "recent_proposals": recent,
                           "watches_with_news": [w for w in watches.listing(store)["watches"] if w.get("last_news")][:5]}
    if not hit:
        out["radar"] = radar.plan(store, limit=5, remember=False)["gaps"]
        asked = [w for w in (app, space, project) if w]
        out["unresolved"] = bool(asked) and not any(_norm(w) in FAMILY_SPACES or w.strip().lower() in FAMILY_SPACES for w in asked)
    return out
