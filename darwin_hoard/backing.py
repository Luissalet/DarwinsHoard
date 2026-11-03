"""Backing of a capability: «this node of the tree really works», with the proof attached.

A capability name in the tree only says that somebody declared it (a manifest) or that Faustus sees a tool with that name.
It does not say the thing works. A node counts as *backed* only when it has a row here with at least one evidence link:

* ``commit``  - a commit hash, optionally ``repo@hash`` (code proof, not a functional test);
* ``test``    - a test file or ``file::test_name`` that exercises it;
* ``qa_file`` - a QA report or recorded check (a file path) that shows it working.

Marking a node as implemented without evidence is refused. The rows live apart from the tree on purpose: a tree refresh
rewrites the nodes, and the proof must survive it. Every change is written to ``history``."""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from .errors import DarwinError
from .store import Store, _j

EVIDENCE_KINDS = ("commit", "test", "qa_file")
_COMMIT = re.compile(r"^(?:[\w.\-/' ]+@)?[0-9a-f]{7,40}$", re.I)
_PATHISH = re.compile(r"[\\/]|\.[A-Za-z0-9]{1,6}($|::)|::")


def normalize_evidence(items: Any) -> list[dict[str, str]]:
    """Validate the evidence links. Raises ``DarwinError`` (``invalid``) naming the first bad one; an empty list is bad."""
    if not isinstance(items, (list, tuple)) or not items:
        raise DarwinError("invalid", "A capability can only be marked implemented with evidence.",
                          "Give at least one link: {kind: commit|test|qa_file, ref: ...}.")
    out: list[dict[str, str]] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise DarwinError("invalid", f"Evidence #{i + 1} must be an object with kind and ref.")
        kind = str(raw.get("kind") or "").strip()
        ref = str(raw.get("ref") or "").strip()
        if kind not in EVIDENCE_KINDS:
            raise DarwinError("invalid", f"Evidence #{i + 1}: kind must be one of {', '.join(EVIDENCE_KINDS)}.")
        if not ref:
            raise DarwinError("invalid", f"Evidence #{i + 1}: ref is empty.")
        if kind == "commit" and not _COMMIT.match(ref):
            raise DarwinError("invalid", f"Evidence #{i + 1}: «{ref}» is not a commit hash (7-40 hex digits, optionally repo@hash).")
        if kind in ("test", "qa_file") and not _PATHISH.search(ref):
            raise DarwinError("invalid", f"Evidence #{i + 1}: «{ref}» does not look like a file path.",
                              "Use a path such as tests/test_x.py::test_y or docs/qa-2026-11-03.md.")
        item = {"kind": kind, "ref": ref}
        note = str(raw.get("note") or "").strip()
        if note:
            item["note"] = note[:300]
        if item not in out:
            out.append(item)
    return out


def all_backing(store: Store) -> dict[str, dict[str, Any]]:
    return {r["capability_key"]: r for r in store.q("SELECT * FROM capability_backing")}


def backing_of(store: Store, key: str) -> Optional[dict[str, Any]]:
    return store.one("SELECT * FROM capability_backing WHERE capability_key=?", (key,))


def is_backed(row: Optional[dict[str, Any]]) -> bool:
    """A row only counts with evidence; a hand-edited row without it is ignored, never trusted."""
    ev = (row or {}).get("evidence")
    return isinstance(ev, list) and any(isinstance(e, dict) and e.get("kind") in EVIDENCE_KINDS and e.get("ref") for e in ev)


def mark(store: Store, key: str, *, implemented: bool, evidence: Any = None, note: str = "", by: str = "agent") -> dict[str, Any]:
    node = store.one("SELECT id, key, name, level, app_id FROM capabilities WHERE key=?", (key,))
    if node is None:
        raise DarwinError("not_found", f"No capability node {key}.", "Look it up with darwin_capability_find or darwin_tree.")
    if node["level"] == "root":
        raise DarwinError("invalid", "The root of the tree is not a capability.")
    now = time.time()
    before = backing_of(store, key)
    if not implemented:
        with store.tx() as c:
            c.execute("DELETE FROM capability_backing WHERE capability_key=?", (key,))
            if before:
                c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('capability_backing',?,?,?,?,?,?,?)",
                          (node["id"], "implemented", "yes", "no", now, by, note))
        return {"key": key, "implemented": False, "changed": before is not None}
    ev = normalize_evidence(evidence)
    with store.tx() as c:
        if before:
            c.execute("UPDATE capability_backing SET evidence=?, note=?, by=?, updated=? WHERE capability_key=?", (_j(ev), note, by, now, key))
        else:
            c.execute("INSERT INTO capability_backing(capability_key, evidence, note, by, created, updated) VALUES (?,?,?,?,?,?)",
                      (key, _j(ev), note, by, now, now))
        c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('capability_backing',?,?,?,?,?,?,?)",
                  (node["id"], "implemented", "yes" if before else "no", "yes", now, by, note))
    return {"key": key, "name": node["name"], "implemented": True, "changed": True, "evidence": ev}
