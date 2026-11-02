"""Darwin in Faustus's Brain (``darwin_brain_export``): Markdown notes in the Brain's vault, linked with ``[[wikilinks]]``.

The Brain is a folder of Markdown notes; free notes under ``Notes/`` are indexed as they are on its next sync. Darwin
writes ``Notes/Darwin/``: an index (``Darwin.md``), one note per app with what was proposed for it, delivered to it and
what it still lacks, and one note per *live* discovery (open, accepted or integrated) with its genealogy and score. Every
note carries ``generated_by: darwins-hoard`` in its front matter; only those notes are overwritten or removed, so a
note a person wrote in that folder is never touched."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from . import fitness as fit
from . import query
from .store import Store

MARK = "generated_by: darwins-hoard"
LIVE = {"integrada", "mixta", "parcial", "aceptada", "en_marcha", "pendiente", "investigando", "debatida", "aplazada"}
STATE_ES = {"integrada": "integrado", "mixta": "en parte", "parcial": "parcial", "aceptada": "aceptado", "en_marcha": "en marcha",
            "pendiente": "pendiente", "investigando": "investigando", "debatida": "debatido", "aplazada": "aplazado",
            "descartada": "descartado", "cubierta": "ya cubierto", "sin_propuesta": "sin propuesta"}


def safe_name(text: str, limit: int = 90) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\[\]#^]+', " ", text or "").strip().strip(".")
    return re.sub(r"\s+", " ", name)[:limit].strip() or "sin nombre"


def plain(text: Any) -> str:
    """Text for a note body: a "#123" or "#tag" from a radar line would become a Brain tag, so the hash goes."""
    return re.sub(r"(?<!\S)#(?=\w)", "", str(text or ""))


def _front(kind: str, extra: dict[str, Any]) -> str:
    lines = ["---", MARK, f"darwin_kind: {kind}", f"updated: {time.strftime('%Y-%m-%d %H:%M')}"]
    lines += [f"{k}: {v}" for k, v in extra.items() if v not in (None, "")]
    return "\n".join(lines + ["---", ""])


def _write(path: Path, text: str, written: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
        if MARK not in head:
            return  # a person's note with the same name: never overwritten
    path.write_text(text, encoding="utf-8")
    written.add(str(path.resolve()))


def export(store: Store, vault_owner_dir: Path) -> dict[str, Any]:
    root = Path(vault_owner_dir) / "Notes" / "Darwin"
    names = {r["app_id"]: r["name"] for r in store.q("SELECT app_id, name FROM capabilities WHERE level IN ('app','root') AND app_id IS NOT NULL")}
    app_note = lambda app: f"Darwin · {safe_name(names.get(app, app))}"  # noqa: E731
    found = query.find(store, limit=100000, with_fitness=True)["items"]
    live = [i for i in found if i["state"] in LIVE]
    gaps = store.q("SELECT id, title, detail, target FROM gaps WHERE state='abierta' ORDER BY target, id")
    written: set[str] = set()
    disc_note: dict[int, str] = {}
    for i in live:
        label = i.get("repo") or i.get("title") or i.get("url") or f"#{i['id']}"
        disc_note[i["id"]] = f"Darwin {i['id']} · {safe_name(label, 70)}"

    # one note per live discovery
    for i in live:
        g = query.genealogy(store, source_id=i["id"]) or {}
        src = g.get("source") or {}
        lines = [_front("discovery", {"darwin_id": i["id"], "state": i["state"], "fitness": i.get("fitness")}),
                 f"# {plain(src.get('title') or src.get('repo') or src.get('url'))}", ""]
        if src.get("url"):
            lines.append(f"Enlace: {src['url']}")
        lines.append(f"Estado: {STATE_ES.get(i['state'], i['state'])}" + (f" · puntuación {i['fitness']}/100" if i.get("fitness") else ""))
        if src.get("summary"):
            lines += ["", plain(src["summary"][:800])]
        props = g.get("proposals") or []
        if props:
            lines += ["", "## Propuestas"]
            lines += [f"- [[{app_note(p['target'])}]]: {STATE_ES.get(p['state'], p['state'])}" + (f" — {plain(p['reason'])}" if p.get("reason") else "")
                      for p in props if p.get("target")]
        dels = g.get("deliveries") or []
        if dels:
            lines += ["", "## Entregas"]
            for d in dels:
                anc = ((d.get("evidence") or {}).get("commit_ancestry") or {}) if isinstance(d.get("evidence"), dict) else {}
                proof = {"integrated": "commit en main", "not_in_main": "commit fuera de main"}.get(anc.get("state"), "según documentos")
                lines.append(f"- [[{app_note(d['target'])}]]: {d.get('implementation')} · {d.get('commit_sha') or 'sin commit'} · {proof}")
        if i.get("fitness_reasons"):
            lines += ["", "## Por qué interesa", *[f"- {plain(r)}" for r in i["fitness_reasons"]]]
        lines += ["", "Ver: [[Darwin]]", ""]
        _write(root / "Descubrimientos" / f"{disc_note[i['id']]}.md", "\n".join(lines), written)

    # one note per app
    by_app: dict[str, list[dict[str, Any]]] = {}
    for i in live:
        for t in i.get("targets") or []:
            by_app.setdefault(t, []).append(i)
    gaps_by_app: dict[str, list[dict[str, Any]]] = {}
    for gp in gaps:
        gaps_by_app.setdefault(gp["target"] or "", []).append(gp)
    for app in sorted(set(by_app) | {a for a in gaps_by_app if a}):
        items = sorted(by_app.get(app, []), key=lambda x: (-(x.get("fitness") or 0), x["id"]))
        done = [x for x in items if x["state"] in ("integrada", "mixta", "parcial")]
        open_ = [x for x in items if x not in done]
        lines = [_front("app", {"app": app}), f"# {names.get(app, app)} en Darwin", ""]
        if open_:
            lines += ["## Propuesto, sin integrar (por puntuación)"]
            lines += [f"- [[{disc_note[x['id']]}]] · {STATE_ES.get(x['state'], x['state'])}" + (f" · {x['fitness']}" if x.get("fitness") else "") for x in open_[:80]]
        if done:
            lines += ["", "## Integrado"] + [f"- [[{disc_note[x['id']]}]]" for x in done[:120]]
        if gaps_by_app.get(app):
            lines += ["", "## Carencias", *[f"- {plain(g['title'])}" for g in gaps_by_app[app]]]
        lines += ["", "Ver: [[Darwin]]", ""]
        _write(root / "Apps" / f"{app_note(app)}.md", "\n".join(lines), written)

    # index
    counts: dict[str, int] = {}
    for i in found:
        counts[i["state"]] = counts.get(i["state"], 0) + 1
    top = sorted([i for i in live if i.get("fitness")], key=lambda x: -x["fitness"])[:15]
    lines = [_front("index", {}), "# Darwin", "",
             "Descubrimientos (repos, artículos, posts, ideas) para Faustus y los Hoards: de dónde vienen, qué se propuso para qué app y qué se entregó. "
             "Generado por Darwin's Hoard; se reescribe en cada exportación.", "",
             "## Estado", *[f"- {STATE_ES.get(k, k)}: {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])], "",
             "## Lo más interesante sin integrar", *[f"- [[{disc_note[x['id']]}]] · {x['fitness']}" for x in top], "",
             "## Por app", *[f"- [[{app_note(a)}]]" for a in sorted(set(by_app) | {a for a in gaps_by_app if a}, key=lambda a: names.get(a, a))], ""]
    if gaps_by_app.get(""):
        lines += ["## Carencias sin app", *[f"- {plain(g['title'])}" for g in gaps_by_app[""]], ""]
    _write(root / "Darwin.md", "\n".join(lines), written)

    # remove Darwin's own notes that are no longer exported
    removed = 0
    if root.exists():
        for p in root.rglob("*.md"):
            if str(p.resolve()) in written:
                continue
            try:
                if MARK in p.read_text(encoding="utf-8", errors="replace")[:400]:
                    p.unlink()
                    removed += 1
            except OSError:
                pass
    return {"folder": str(root), "notes": len(written), "discoveries": len(live), "apps": len(set(by_app) | {a for a in gaps_by_app if a}),
            "removed": removed}
