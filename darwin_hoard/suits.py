"""The library of suits (trajes): reusable work configurations for a kind of engagement.

A suit says, for one kind of job: the objective, the inputs and how each is identified, the domain concepts, the operations
it uses (each one a reference to a node of the capability tree), the views to inspect, the acceptance criteria of the
deliverable, an execution recipe and the points where a model has to judge. The library answers «what engagements can you
solve?» and is honest about it. Status of a suit:

* ``proposed``  - nothing it needs is backed yet;
* ``partial``   - some referenced capabilities are backed, others are missing or only declared;
* ``backed``    - every required operation points to a node that exists in the tree **and** is marked implemented with
  evidence (a commit, a test or a QA file; see ``backing.py``). A capability name alone proves nothing;
* ``evaluated`` - results of an evaluation done in Pygmalion's Hoard were imported (``import_evaluation``). The backing
  state at the time of import is kept next to it, so «evaluated» never hides that something was missing."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Optional

from .backing import all_backing, is_backed
from .errors import DarwinError
from .store import Store, _j

STATUSES = ("proposed", "partial", "backed", "evaluated")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
JSON_FIELDS = ("inputs", "concepts", "operations", "views", "acceptance", "recipe", "judgement")
EVAL_FORMAT = "pygmalion-suit-eval/1"
OP_STATES = ("backed", "unproven", "missing")


# ---------------------------------------------------------------------- pure status computation

def operation_states(operations: list[dict[str, Any]], nodes: dict[str, dict[str, Any]], backing: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per operation: ``backed`` (node exists and has evidence), ``unproven`` (node exists, no evidence) or ``missing``
    (no reference, or the node is not in the tree)."""
    out = []
    for op in operations:
        key = (op.get("capability_key") or "").strip()
        node = nodes.get(key) if key else None
        row = backing.get(key) if key else None
        if node is None:
            state, evidence = "missing", []
        elif is_backed(row):
            state, evidence = "backed", row["evidence"]
        else:
            state, evidence = "unproven", []
        out.append({"name": op.get("name") or key, "capability_key": key, "required": op.get("required", True) is not False,
                    "state": state, "evidence": evidence, "node": ({"key": node["key"], "name": node["name"], "level": node["level"],
                                                                     "app_id": node["app_id"], "operation": node["operation"]} if node else None),
                    "note": op.get("note") or "", "missing_reason": op.get("missing_reason") or ""})
    return out


def compute_status(suit: dict[str, Any], nodes: dict[str, dict[str, Any]], backing: dict[str, dict[str, Any]],
                   evaluation: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ops = operation_states(suit.get("operations") or [], nodes, backing)
    required = [o for o in ops if o["required"]]
    backed = [o for o in required if o["state"] == "backed"]
    if not required or not backed:
        base = "proposed"
    elif len(backed) == len(required):
        base = "backed"
    else:
        base = "partial"
    status = "evaluated" if evaluation else base
    return {"status": status, "backing": base, "operations": ops, "required": len(required), "backed": len(backed),
            "unproven": [o["name"] for o in required if o["state"] == "unproven"],
            "missing": [o["name"] for o in required if o["state"] == "missing"], "evaluated": bool(evaluation)}


# ---------------------------------------------------------------------- reading

def _decode(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for f in JSON_FIELDS:
        try:
            out[f] = json.loads(out[f]) if out.get(f) else []
        except ValueError:
            out[f] = []
    return out


def _nodes(store: Store) -> dict[str, dict[str, Any]]:
    return {r["key"]: r for r in store.q("SELECT key, name, level, app_id, operation FROM capabilities")}


def latest_evaluation(store: Store, suit_id: int) -> Optional[dict[str, Any]]:
    row = store.one("SELECT * FROM suit_evaluations WHERE suit_id=? ORDER BY imported DESC, id DESC LIMIT 1", (suit_id,))
    if not row:
        return None
    payload = json.loads(row["payload"])
    return {"eval_id": row["eval_id"], "imported": row["imported"], "sha256": row["sha256"],
            "backing_at_import": json.loads(row["backing_at_import"] or "null"), "payload": payload}


def _view(store: Store, suit: dict[str, Any], nodes: dict, backing: dict, *, full: bool) -> dict[str, Any]:
    ev = latest_evaluation(store, suit["id"])
    st = compute_status(suit, nodes, backing, ev)
    out = dict(suit)
    out["state"] = st
    out["status"] = st["status"]
    if ev:
        summary = ev["payload"].get("aggregate") or {}
        out["evaluation"] = {"eval_id": ev["eval_id"], "imported": ev["imported"], "backing_at_import": ev["backing_at_import"],
                             "cases_scored": ev["payload"].get("cases_scored"), "excluded": ev["payload"].get("excluded") or [],
                             "arms": sorted(summary), **({"payload": ev["payload"]} if full else {})}
    else:
        out["evaluation"] = None
    return out


def get_suit(store: Store, slug: str) -> dict[str, Any]:
    row = store.one("SELECT * FROM suits WHERE slug=?", (slug,))
    if not row:
        raise DarwinError("not_found", f"No suit «{slug}».", "List them with darwin_suits.")
    return _view(store, _decode(row), _nodes(store), all_backing(store), full=True)


def list_suits(store: Store, status: str = "") -> dict[str, Any]:
    """The «what engagements can you solve» view: every suit with its status, and the counts per status."""
    if status and status not in STATUSES:
        raise DarwinError("invalid", f"status must be one of {', '.join(STATUSES)}.")
    nodes, backing = _nodes(store), all_backing(store)
    items, counts = [], {s: 0 for s in STATUSES}
    for row in store.q("SELECT * FROM suits ORDER BY name COLLATE NOCASE"):
        v = _view(store, _decode(row), nodes, backing, full=False)
        counts[v["status"]] += 1
        if status and v["status"] != status:
            continue
        st = v["state"]
        items.append({"slug": v["slug"], "name": v["name"], "objective": v["objective"], "status": v["status"], "backing": st["backing"],
                      "required": st["required"], "backed": st["backed"], "missing": st["missing"], "unproven": st["unproven"],
                      "evaluated": st["evaluated"], "evaluation": v["evaluation"], "updated": v["updated"]})
    return {"suits": items, "counts": counts, "total": sum(counts.values())}


# ---------------------------------------------------------------------- writing

def _clean_list(value: Any, field: str, required_key: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DarwinError("invalid", f"{field} must be a list.")
    out = []
    for i, item in enumerate(value):
        if isinstance(item, str):
            item = {required_key: item}
        if not isinstance(item, dict) or not str(item.get(required_key) or "").strip():
            raise DarwinError("invalid", f"{field} #{i + 1} needs «{required_key}».")
        out.append(item)
    return out


def save_suit(store: Store, data: dict[str, Any], *, by: str = "agent", partial: bool = False) -> dict[str, Any]:
    """Create or update a suit by slug. With ``partial`` only the given fields change."""
    slug = str(data.get("slug") or "").strip().lower()
    if not SLUG.match(slug):
        raise DarwinError("invalid", "slug must be 3-64 characters: lower case letters, digits and hyphens.")
    existing = store.one("SELECT * FROM suits WHERE slug=?", (slug,))
    if existing is None and not str(data.get("name") or "").strip():
        raise DarwinError("invalid", "A new suit needs a name.")
    spec = {"inputs": "name", "concepts": "term", "operations": "name", "views": "name", "acceptance": "id", "recipe": "step", "judgement": "point"}
    values: dict[str, Any] = {}
    for f, req in spec.items():
        if f in data and data[f] is not None:
            values[f] = _clean_list(data[f], f, req)
    for op in values.get("operations", []):
        if op.get("capability_key") is not None and not isinstance(op["capability_key"], str):
            raise DarwinError("invalid", "operations[].capability_key must be a string.")
        if not (op.get("capability_key") or "").strip() and not (op.get("missing_reason") or "").strip():
            op["missing_reason"] = "No capability exists for this yet."
    for f in ("name", "objective", "origin", "proposal"):
        if f in data and data[f] is not None:
            values[f] = str(data[f]).strip()
    now = time.time()
    if existing is None:
        cols = {"slug": slug, "name": values.get("name", ""), "objective": values.get("objective", ""), "origin": values.get("origin", ""),
                "proposal": values.get("proposal", ""), **{f: _j(values.get(f, [])) for f in spec}, "created": now, "updated": now}
        with store.tx() as c:
            cur = c.execute(f"INSERT INTO suits({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
            c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('suits',?,?,?,?,?,?,?)",
                      (cur.lastrowid, "created", None, slug, now, by, ""))
    else:
        if not values:
            return get_suit(store, slug)
        sets = {f: (_j(v) if f in spec else v) for f, v in values.items()}
        sets["updated"] = now
        with store.tx() as c:
            c.execute(f"UPDATE suits SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), existing["id"]))
            c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('suits',?,?,?,?,?,?,?)",
                      (existing["id"], "updated", None, ",".join(sorted(values)), now, by, ""))
    return get_suit(store, slug)


def delete_suit(store: Store, slug: str, *, by: str = "agent") -> dict[str, Any]:
    row = store.one("SELECT id FROM suits WHERE slug=?", (slug,))
    if not row:
        raise DarwinError("not_found", f"No suit «{slug}».")
    with store.tx() as c:
        c.execute("DELETE FROM suit_evaluations WHERE suit_id=?", (row["id"],))
        c.execute("DELETE FROM suits WHERE id=?", (row["id"],))
        c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('suits',?,?,?,?,?,?,?)",
                  (row["id"], "deleted", slug, None, time.time(), by, ""))
    return {"deleted": slug}


# ---------------------------------------------------------------------- evaluation results from Pygmalion

def validate_evaluation(payload: Any) -> dict[str, Any]:
    """The contract with Pygmalion's Hoard (``pygmalion-suit-eval/1``). Refuses anything that does not carry scored results."""
    if not isinstance(payload, dict):
        raise DarwinError("invalid", "The evaluation must be a JSON object.")
    if payload.get("format") != EVAL_FORMAT:
        raise DarwinError("invalid", f"Unknown format «{payload.get('format')}»; expected {EVAL_FORMAT}.")
    for f in ("suit", "evaluation_id"):
        if not str(payload.get(f) or "").strip():
            raise DarwinError("invalid", f"The evaluation has no «{f}».")
    agg = payload.get("aggregate")
    if not isinstance(agg, dict) or not agg:
        raise DarwinError("invalid", "The evaluation has no aggregate per arm.")
    scored = payload.get("cases_scored")
    if not isinstance(scored, int) or isinstance(scored, bool) or scored < 1:
        raise DarwinError("invalid", "An evaluation with no scored case cannot mark a suit as evaluated.",
                          "Cases used to build the improvement are excluded from the score; at least one other case is needed.")
    for arm, a in agg.items():
        if not isinstance(a, dict) or not isinstance(a.get("cases"), int):
            raise DarwinError("invalid", f"Arm «{arm}» has no case count.")
    return payload


def import_evaluation(store: Store, payload: Any, *, slug: str = "", by: str = "pygmalion") -> dict[str, Any]:
    """Store an evaluation for a suit (idempotent on suit + evaluation_id). The suit becomes ``evaluated``."""
    payload = validate_evaluation(payload)
    target = (slug or payload["suit"]).strip().lower()
    suit = store.one("SELECT id, slug FROM suits WHERE slug=?", (target,))
    if not suit:
        raise DarwinError("not_found", f"No suit «{target}» in the library.", "Create it with darwin_suit_save first.")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    before = get_suit(store, target)["state"]
    now = time.time()
    with store.tx() as c:
        row = c.execute("SELECT id FROM suit_evaluations WHERE suit_id=? AND eval_id=?", (suit["id"], str(payload["evaluation_id"]))).fetchone()
        if row:
            c.execute("UPDATE suit_evaluations SET payload=?, sha256=?, backing_at_import=?, imported=? WHERE id=?",
                      (raw, sha, _j({"backing": before["backing"], "missing": before["missing"], "unproven": before["unproven"]}), now, row["id"]))
        else:
            c.execute("INSERT INTO suit_evaluations(suit_id, eval_id, payload, sha256, backing_at_import, imported) VALUES (?,?,?,?,?,?)",
                      (suit["id"], str(payload["evaluation_id"]), raw, sha,
                       _j({"backing": before["backing"], "missing": before["missing"], "unproven": before["unproven"]}), now))
        c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('suits',?,?,?,?,?,?,?)",
                  (suit["id"], "status", before["status"], "evaluated", now, by, str(payload["evaluation_id"])))
    return {"imported": True, "replaced": bool(row), "suit": get_suit(store, target)}
