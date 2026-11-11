"""Gaps from the Hoards' own objective lists (``OBJETIVOS.md``).

A Hoard whose OBJETIVOS.md is a plain list (``- item``, ``- [ ] item`` or ``1. **Title.** text``) states things it does not
do yet: each item becomes an open gap for that app, so the radar and ``darwin_ask`` know what is wanted. Long running
logs (Faustus's and Writer's OBJETIVOS are thousands of lines of history) are not lists and are skipped. Idempotent:
an item already imported is left alone, and a gap whose item disappeared from its file (done, or dropped) is closed."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from .store import Store

MAX_LINES = 120          # longer files are logs, not lists
MAX_ITEMS = 40
ITEM = re.compile(r"^(?:[-*]|\d+[.)])\s+(?:\[( |x|X|~)\]\s+)?(.+)$")


def parse(text: str) -> list[dict[str, str]]:
    items: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = ITEM.match(line)
        if m and not raw.startswith((" ", "\t")):
            current = {"done": (m.group(1) or "").strip().lower() == "x", "lines": [m.group(2).strip()]}
            items.append(current)
        elif current and raw.startswith((" ", "\t")) and line.strip():
            current["lines"].append(line.strip())
        elif not line.strip() or line.startswith("#"):
            current = None
    out = []
    for it in items[:MAX_ITEMS]:
        if it["done"]:
            continue
        body = " ".join(it["lines"])
        bold = re.match(r"\*\*(.+?)\*\*\s*(.*)", body)
        title = (bold.group(1) if bold else re.split(r"(?<=[.:;])\s", body, maxsplit=1)[0]).strip().rstrip(".:")
        plain = re.sub(r"\*\*|`", "", body)
        out.append({"title": re.sub(r"\*\*|`", "", title)[:160], "detail": plain[:1200]})
    return out


def app_of(repo_dir: Path, known_apps: set[str]) -> Optional[str]:
    try:
        app = json.loads((repo_dir / "faustus-plugin.json").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError):
        return None
    for candidate in (app, (app or "").removesuffix("-hoard"), (app or "").replace("-", "")):
        if candidate and candidate in known_apps:
            return candidate
    return app or None


def import_objectives(store: Store, hoards_root: Path, *, extra_files: Optional[list[tuple[Path, str]]] = None,
                      chat: Optional[Any] = None, days: Optional[int] = None, max_new: Optional[int] = None) -> dict[str, Any]:
    """Lists become one gap per item. A file longer than ``MAX_LINES`` is a log: it goes through ``gaps_log`` (candidates by
    cue, sorted by the local model when ``chat`` is given). ``extra_files`` are ``(path, app)`` logs outside the Hoards folder
    (Faustus's own OBJETIVOS.md)."""
    from . import gaps_log
    known = {r["app_id"] for r in store.q("SELECT DISTINCT app_id FROM capabilities WHERE app_id IS NOT NULL")}
    files = sorted({*hoards_root.glob("*/OBJETIVOS.md"), *hoards_root.glob("*/*/OBJETIVOS.md")})
    forced = {Path(p): a for p, a in (extra_files or [])}
    files = sorted({*files, *forced})
    added = closed = kept = 0
    report: dict[str, Any] = {}
    log_totals = {"added": 0, "closed": 0, "pending": 0}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if path in forced or len(text.splitlines()) > MAX_LINES:
            res = gaps_log.import_log(store, path, forced.get(path) or app_of(path.parent, known), chat=chat,
                                      days=days or gaps_log.DEFAULT_DAYS, max_new=max_new or gaps_log.MAX_NEW_PER_RUN)
            report[str(path)] = {"log": True, **res}
            for k in log_totals:
                log_totals[k] += int(res.get(k) or 0)
            continue
        app = app_of(path.parent, known)
        items = parse(text)
        titles = {i["title"] for i in items}
        source = str(path)
        existing = {r["title"]: r for r in store.q("SELECT id, title, state FROM gaps WHERE json_extract(watch,'$.file')=? "
                                                 "AND COALESCE(json_extract(watch,'$.from'),'objetivos')='objetivos'", (source,))}
        for it in items:
            if it["title"] in existing:
                kept += 1
                continue
            store.add_gap(title=it["title"], detail=it["detail"], target=app or "", watch={"file": source, "from": "objetivos"})
            added += 1
        for title, row in existing.items():
            if title not in titles and row["state"] == "abierta":
                with store.tx() as c:
                    c.execute("UPDATE gaps SET state='cerrada', updated=? WHERE id=?", (time.time(), row["id"]))
                closed += 1
        report[str(path)] = {"app": app, "items": len(items)}
    return {"added": added + log_totals["added"], "kept": kept, "closed": closed + log_totals["closed"],
            "log_added": log_totals["added"], "log_pending": log_totals["pending"], "files": report}
