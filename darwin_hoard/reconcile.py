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
                if old["reason"] == "semantic" and _semantic_valid(store, backing, old):
                    continue  # found by meaning, not by name: it stays while its capability still stands
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


def _semantic_valid(store: Store, backing: dict[str, dict[str, Any]], flag: dict[str, Any]) -> bool:
    """A flag found by meaning stays while the gap is open and its capability still has proof (evidence or a tested node)."""
    key = flag.get("capability_key")
    if not key or not store.one("SELECT 1 AS x FROM gaps WHERE id=? AND state='abierta'", (flag["gap_id"],)):
        return False
    node = store.one("SELECT evidence FROM capabilities WHERE key=?", (key,))
    return bool(node) and (is_backed(backing.get(key)) or node["evidence"] == "probada")


# ---------------------------------------------------------------------- by meaning

SEM_SCHEMA = {"type": "object", "properties": {"match": {"type": "integer"}, "confidence": {"type": "string"}, "reason": {"type": "string"}},
              "required": ["match", "confidence"]}
SEM_SYSTEM = ("Eres Darwin, el archivo de la familia Faustus/Hoards. Una carencia es algo que Luis quiere y que, según su apunte, "
              "ninguna app hace. Se te da la carencia y varias capacidades que SÍ existen, con prueba. Decide si alguna de ellas "
              "hace ya lo que pide la carencia, entendiendo el significado y no solo las palabras. Devuelve JSON {match, "
              "confidence, reason}: match es el número de la capacidad que ya lo hace (0 si ninguna), confidence es "
              "'alta' solo si la capacidad cubre claramente lo que pide la carencia entera, si no 'media' o 'baja', y reason "
              "una frase en castellano. Ante la duda, match 0.")
SEM_POOL = 8
SEM_BATCH_LIMIT = 40


def _shortlist(gap: dict[str, Any], pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gw = _gap_words(gap)
    scored = []
    for n in pool:
        words = {w for w in _name_words(n["name"] + " " + (n.get("detail") or "")[:200]) if w not in _GENERIC and w not in STOPWORDS and len(w) >= 3}
        shared = words & gw
        if not shared:
            continue
        same_app = 1.5 if gap.get("target") and n["app_id"] == gap["target"] else (0.0 if not gap.get("target") else -0.5)
        scored.append((len(shared) + same_app, n))
    scored.sort(key=lambda t: -t[0])
    return [n for s, n in scored if s >= 1][:SEM_POOL]


def semantic(store: Store, chat: Any, *, limit: int = SEM_BATCH_LIMIT) -> dict[str, Any]:
    """Flag open gaps whose meaning a proven capability already covers. The local model reads the gap and a short list of
    candidate capabilities (those with evidence, or tested); the answer is a flag «possibly stale», never a closure. A gap
    is asked again only when its text or its candidates change; a flag a person dismissed is not raised again for that
    capability."""
    import hashlib
    backing = all_backing(store)
    nodes = store.q("SELECT key, name, level, app_id, evidence, detail FROM capabilities WHERE level IN ('capability','tool')")
    pool = [n for n in nodes if is_backed(backing.get(n["key"])) or n["evidence"] == "probada"]
    checked = dict(store.get_meta("semantic_checked", {}) or {})
    flags = {r["gap_id"]: r for r in store.q("SELECT * FROM gap_flags")}
    asked = flagged = skipped = failed = 0
    new_ids: list[int] = []
    now = time.time()
    for gap in store.q("SELECT id, title, detail, target FROM gaps WHERE state='abierta' ORDER BY updated DESC"):
        if asked >= limit:
            break
        old = flags.get(gap["id"])
        if old and old["status"] == "possibly_stale":
            continue
        short = _shortlist(gap, pool)
        sig = hashlib.sha1((gap["title"] + (gap.get("detail") or "") + "|".join(n["key"] for n in short)).encode("utf-8")).hexdigest()[:16]
        if not short or checked.get(str(gap["id"])) == sig:
            skipped += 1
            continue
        listing_txt = "\n".join(f"{i}. {n['name']} (app {n['app_id']}): {(n.get('detail') or '')[:160]}" for i, n in enumerate(short, 1))
        asked += 1
        res = chat([{"role": "system", "content": SEM_SYSTEM},
                    {"role": "user", "content": f"Carencia: {gap['title']}\n{(gap.get('detail') or '')[:600]}\n\nCapacidades con prueba:\n{listing_txt}"}],
                   json=SEM_SCHEMA, effort="low", max_tokens=400, temperature=0.1, timeout=120.0)
        data = res.get("json") if res.get("ok") and isinstance(res.get("json"), dict) else None
        if data is None:
            failed += 1
            continue
        checked[str(gap["id"])] = sig
        idx = data.get("match")
        if not isinstance(idx, int) or not 1 <= idx <= len(short) or str(data.get("confidence", "")).lower() != "alta":
            continue
        node = short[idx - 1]
        if old and old["status"] == "dismissed" and old["capability_key"] == node["key"]:
            continue
        ev = backing[node["key"]]["evidence"] if is_backed(backing.get(node["key"])) else [{"kind": "test", "ref": f"tree: {node['key']} (probada)"}]
        with store.tx() as c:
            c.execute("INSERT INTO gap_flags(gap_id, status, capability_key, evidence, reason, matched, flagged, updated) VALUES (?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(gap_id) DO UPDATE SET status='possibly_stale', capability_key=excluded.capability_key, evidence=excluded.evidence, "
                      "reason='semantic', matched=excluded.matched, updated=excluded.updated",
                      (gap["id"], "possibly_stale", node["key"], _j(ev), "semantic", _j([str(data.get("reason") or "")[:300]]), now, now))
        flagged += 1
        new_ids.append(gap["id"])
    store.set_meta("semantic_checked", checked)
    return {"asked": asked, "flagged": flagged, "newly_flagged": new_ids, "unchanged_or_no_candidates": skipped, "model_failed": failed,
            "pool": len(pool)}


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
