"""Skills improved by delivered repositories: documented links and labelled suggestions.

Reads the published library and Hub shelves; never changes either or starts apps.
Explicit links live in delivery evidence, beside the existing commit evidence.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlencode

from . import coverage
from .errors import DarwinError
from .hoard_link import skills


def library(config) -> list[dict[str, Any]]:
    folder = skills.find_library(config.faustus_dir)
    return skills.library_rows(folder) if folder else []


def link(store, config, *, delivery_id: int, slug: str, reason: str = "", on: bool = True) -> dict[str, Any]:
    row = next((r for r in library(config) if r["slug"] == slug), None)
    if on and row is None:
        raise DarwinError("not_found", "The published skill is not in the library.")
    if on and not reason.strip():
        raise DarwinError("invalid", "Describe which part of the skill the delivery improves.")
    with store.tx() as c:
        delivery = c.execute("SELECT evidence FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if delivery is None:
            raise DarwinError("not_found", "No such delivery.")
        evidence = json.loads(delivery["evidence"] or "{}")
        impacts = [r for r in evidence.get("skill_impacts", []) if r.get("slug") != slug]
        if on:
            impacts.append({"slug": slug, "reason": reason.strip(), "version": row["version"],
                            "sha256": hashlib.sha256(row["text"].encode("utf-8")).hexdigest(), "at": time.time()})
        evidence["skill_impacts"] = impacts
        c.execute("UPDATE deliveries SET evidence=? WHERE id=?", (json.dumps(evidence, ensure_ascii=False), delivery_id))
    return {"delivery_id": delivery_id, "skill_impacts": impacts}


def report(store, config, *, source_id: int | None = None, target: str = "", limit: int = 100, offset: int = 0,
           shelves: dict[str, list[str]] | None = None) -> dict[str, Any]:
    rows = library(config)
    by_slug = {r["slug"]: r for r in rows}
    where = ["d.implementation='integrada'", "COALESCE(s.repo,'')<>''"]
    args = []
    if source_id:
        where.append("s.id=?"); args.append(source_id)
    if target:
        where.append("d.target=?"); args.append(target)
    sql = " FROM deliveries d JOIN sources s ON s.id=d.source_id WHERE " + " AND ".join(where)
    total = store.one("SELECT COUNT(*) AS n" + sql, args)["n"]
    deliveries = store.q("SELECT d.*,s.repo AS source_repo,s.title AS source_title,s.summary AS source_summary,s.legacy_radar_no AS radar_no" +
                         sql + " ORDER BY d.id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    items = []
    for d in deliveries:
        explicit = (d.get("evidence") or {}).get("skill_impacts", [])
        linked = []
        for value in explicit:
            skill = by_slug.get(value["slug"])
            current_hash = hashlib.sha256(skill["text"].encode("utf-8")).hexdigest() if skill else None
            linked.append({**value, "status": "documented", "available": skill is not None,
                           "source_changed": current_hash != value.get("sha256"),
                           "on_shelf": value["slug"] in shelves.get(d["target"], []) if shelves is not None else None,
                           "skill_url": "/api/skill-impacts/skill?" + urlencode({"slug": value["slug"]})})
        text = " ".join(str(d.get(k) or "") for k in ("source_repo", "source_title", "source_summary", "capability_key"))
        text += " " + str((d.get("declared") or {}).get("what") or "")
        terms = set(coverage.terms_of(text, max_terms=40))
        candidates = []
        for skill in rows:
            if skill["slug"] in {x["slug"] for x in linked}:
                continue
            on_shelf = skill["slug"] in shelves.get(d["target"], []) if shelves is not None else None
            if (shelves is not None and not on_shelf) or (shelves is None and d["target"] not in skill["apps"]):
                continue
            shared = sorted(terms & set(coverage.terms_of(skill["slug"].replace("-", " ") + " " + skill["description"] + " " + " ".join(skill["tags"]), max_terms=40)))
            if len(shared) < 2:
                continue
            candidates.append({"slug": skill["slug"], "status": "suggested", "shared": shared, "on_shelf": on_shelf,
                               "reason": "Coincidencia de términos: " + ", ".join(shared),
                               "skill_url": "/api/skill-impacts/skill?" + urlencode({"slug": skill["slug"]})})
        candidates.sort(key=lambda r: (-len(r["shared"]), r["slug"]))
        items.append({"delivery_id": d["id"], "source_id": d["source_id"], "repo": d["source_repo"], "title": d["source_title"],
                      "target": d["target"], "radar_no": d["radar_no"], "commit_sha": d["commit_sha"], "target_repo": d["repo"],
                      "verification": d["verification"], "commit_ancestry": (d.get("evidence") or {}).get("commit_ancestry"),
                      "skills": linked, "suggestions": candidates[:3],
                      "status": "documented" if linked else "suggested" if candidates else "unmatched",
                      "shelf_url": config.hub_url + "/api/skills/page?" + urlencode({"app": d["target"]}),
                      "source_url": "/?open=" + str(d["source_id"]) + "#history"})
    return {"items": items, "total": total, "offset": offset, "limit": limit, "library_available": bool(rows),
            "library": [{"slug": r["slug"], "name": r["name"]} for r in rows],
            "shelves_available": shelves is not None,
            "note": "Documented links describe a delivery's contribution. Suggestions are term matches to review; neither changes a skill or proves its improvement."}


def read(config, slug: str) -> dict[str, Any]:
    skill = next((r for r in library(config) if r["slug"] == slug), None)
    if skill is None:
        raise DarwinError("not_found", "The published skill is not in the library.")
    return {k: skill[k] for k in ("slug", "version", "text", "description")}
