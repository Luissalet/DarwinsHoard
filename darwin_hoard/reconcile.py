"""Gap reconciliation: a gap that the tree now answers is flagged as possibly stale instead of being counted as open.

A gap is something wanted that no app does. When the current tree marks a function as implemented **with evidence** (see
``backing.py``) and the gap names that function, the gap is probably old. Darwin never closes it by itself: it keeps the gap
``abierta``, adds a flag with the evidence, and stops counting it as open in the overview, the score of discoveries and the
Brain notes. A person (or an agent that checked) confirms it (``resuelta``) or dismisses the flag (the gap stays open and is
not flagged again for that capability).

Matching, deliberately conservative:

1. the gap names the capability explicitly (``capability_key``) and that node is backed; or
2. the words of a backed capability or tool name are all in the title and detail of the gap (Spanish words are expanded with
   the tree's aliases), and the gap's app, if it has one, is the app of that node.

Only nodes with evidence are candidates: a capability that is merely declared never closes a gap."""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from .backing import all_backing, is_backed
from .store import Store, _j
from .tree import ALIASES, STOPWORDS, folded

_GENERIC = {"tool", "tools", "get", "set", "list", "add", "run", "start", "status", "app", "hoard", "api", "new", "all", "read", "write", "one"}


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", folded(text)) if len(w) >= 2 and w not in STOPWORDS}


def _gap_words(gap: dict[str, Any]) -> set[str]:
    words = _words(f"{gap['title']} {gap.get('detail') or ''}")
    for w in list(words):
        words.update(_stem(x) for x in ALIASES.get(w, "").split())
    return words


def _name_words(name: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", folded(name.replace("_", " ").replace("-", " ")))}


def _node_matches(gap_words: set[str], node: dict[str, Any]) -> Optional[list[str]]:
    words = _name_words(node["name"])
    significant = {w for w in words if w not in _GENERIC and w not in STOPWORDS}
    if not significant or not words <= gap_words | _GENERIC | STOPWORDS:
        return None
    if len(significant) < 2 and max(len(w) for w in significant) < 3:
        return None
    return sorted(significant)


def find_matches(store: Store) -> dict[int, dict[str, Any]]:
    """Per open gap id, the backed capability that answers it (first, most specific match)."""
    backing = all_backing(store)
    backed_keys = [k for k, r in backing.items() if is_backed(r)]
    if not backed_keys:
        return {}
    nodes = {r["key"]: r for r in store.q("SELECT key, name, level, app_id FROM capabilities")}
    candidates = [nodes[k] for k in backed_keys if k in nodes]
    out: dict[int, dict[str, Any]] = {}
    for gap in store.q("SELECT id, title, detail, target, capability_key FROM gaps WHERE state='abierta'"):
        key = gap.get("capability_key")
        if key and key in nodes and is_backed(backing.get(key)):
            out[gap["id"]] = {"capability_key": key, "reason": "capability_key", "matched": [], "name": nodes[key]["name"]}
            continue
        gw = _gap_words(gap)
        best: Optional[tuple[int, dict[str, Any], list[str]]] = None
        for n in candidates:
            if n["level"] not in ("capability", "tool"):
                continue
            if gap.get("target") and n["app_id"] != gap["target"]:
                continue
            m = _node_matches(gw, n)
            if m and (best is None or len(m) > best[0]):
                best = (len(m), n, m)
        if best:
            out[gap["id"]] = {"capability_key": best[1]["key"], "reason": "name_match", "matched": best[2], "name": best[1]["name"]}
    return out


def reconcile(store: Store, *, confirm_ids: Optional[list[int]] = None, dismiss_ids: Optional[list[int]] = None, by: str = "agent") -> dict[str, Any]:
    """Recompute the flags and apply what a person confirmed or dismissed. Returns the reconciled gaps and the open count."""
    now = time.time()
    backing = all_backing(store)
    matches = find_matches(store)
    flags = {r["gap_id"]: r for r in store.q("SELECT * FROM gap_flags")}
    newly, cleared = [], []
    with store.tx() as c:
        for gid, m in matches.items():
            old = flags.get(gid)
            ev = backing[m["capability_key"]]["evidence"]
            if old and old["status"] == "dismissed" and old["capability_key"] == m["capability_key"]:
                continue
            c.execute("INSERT INTO gap_flags(gap_id, status, capability_key, evidence, reason, matched, flagged, updated) VALUES (?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(gap_id) DO UPDATE SET status='possibly_stale', capability_key=excluded.capability_key, evidence=excluded.evidence, "
                      "reason=excluded.reason, matched=excluded.matched, updated=excluded.updated",
                      (gid, "possibly_stale", m["capability_key"], _j(ev), m["reason"], _j(m["matched"]), now, now))
            if not old or old["status"] != "possibly_stale":
                newly.append(gid)
        for gid, old in flags.items():
            if gid not in matches:  # the proof went away (or the gap closed): the flag goes too
                c.execute("DELETE FROM gap_flags WHERE gap_id=?", (gid,))
                cleared.append(gid)
    confirmed, dismissed = [], []
    for gid in confirm_ids or []:
        if store.one("SELECT gap_id FROM gap_flags WHERE gap_id=? AND status='possibly_stale'", (gid,)):
            store.set_state("gaps", gid, "state", "resuelta", by=by, note="confirmed stale by reconciliation")
            confirmed.append(gid)
    for gid in dismiss_ids or []:
        with store.tx() as c:
            if c.execute("UPDATE gap_flags SET status='dismissed', updated=? WHERE gap_id=? AND status='possibly_stale'", (now, gid)).rowcount:
                dismissed.append(gid)
    out = listing(store)
    out.update(newly_flagged=newly, cleared=cleared, confirmed=confirmed, dismissed=dismissed)
    return out


def listing(store: Store) -> dict[str, Any]:
    """The reconciled gaps (possibly stale, with their evidence) and how many gaps are really open."""
    import json
    rows = store.q("SELECT g.id, g.title, g.detail, g.target, g.state, f.capability_key, f.evidence, f.reason, f.matched, f.flagged "
                   "FROM gap_flags f JOIN gaps g ON g.id=f.gap_id WHERE f.status='possibly_stale' AND g.state='abierta' ORDER BY f.flagged DESC")
    for r in rows:
        r["matched"] = json.loads(r["matched"] or "[]")
        name = store.one("SELECT name FROM capabilities WHERE key=?", (r["capability_key"],))
        r["capability_name"] = name["name"] if name else r["capability_key"]
    return {"possibly_stale": rows, "open": store.one("SELECT COUNT(*) AS n FROM gaps WHERE " + _open_sql())["n"],
            "stale_count": len(rows), "total_marked_open": store.one("SELECT COUNT(*) AS n FROM gaps WHERE state='abierta'")["n"]}


def _open_sql() -> str:
    from .store import OPEN_GAP_SQL
    return OPEN_GAP_SQL
