"""Discoveries nobody proposed for an app yet: suggest the app (``darwin_triage``).

For each source without proposals, the material is what Darwin holds about it (title, URL, the chat text and the OCR of
its screenshot) plus the apps whose capabilities share its words (the tree). The family's local model picks one app id
from the real catalogue, or none, and says why in one sentence. A pick becomes a *pending* proposal with origin
``agent`` (Luis's own decisions outrank it and are never overwritten); every verdict, pick or not, is kept on the source
(``meta.triage``) so a discovery is triaged once."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from . import coverage, tree
from .store import Store

ChatFn = Callable[..., dict[str, Any]]
SCHEMA = {"type": "object", "properties": {"app": {"type": ["string", "null"]}, "reason": {"type": "string"},
                                            "useful": {"type": "boolean"}}, "required": ["app", "reason", "useful"]}
SYSTEM = ("Clasificas descubrimientos (repos, posts, artículos) para la familia de apps Faustus/Hoards de Luis. Para cada uno elige "
          "UNA app del catálogo donde aportaría algo concreto, o null si no encaja en ninguna o es ruido (un perfil de X sin "
          "contenido, algo ilegible). Usa solo ids del catálogo. 'reason': una frase en castellano de España con qué aportaría. "
          "'useful': false si es ruido. Devuelve JSON {app, reason, useful}.")


def catalogue(store: Store) -> dict[str, str]:
    rows = store.q("SELECT app_id, name, detail FROM capabilities WHERE level IN ('app','root') AND app_id IS NOT NULL")
    return {r["app_id"]: f"{r['name']}: {(r['detail'] or '')[:110]}" for r in rows}


def pending(store: Store, *, channel: str = "", limit: int = 50) -> list[dict[str, Any]]:
    where = ["NOT EXISTS (SELECT 1 FROM proposals p WHERE p.source_id=s.id)", "json_extract(s.meta,'$.triage') IS NULL"]
    args: list[Any] = []
    if channel:
        where.append("s.id IN (SELECT cs.source_id FROM capture_sources cs JOIN captures c ON c.id=cs.capture_id WHERE c.channel=? "
                     "UNION SELECT source_id FROM captures WHERE channel=?)")
        args += [channel, channel]
    return store.q(f"SELECT s.* FROM sources s WHERE {' AND '.join(where)} ORDER BY s.last_seen DESC LIMIT ?", (*args, limit))


def _material(store: Store, src: dict[str, Any]) -> str:
    caps = store.q("SELECT c.text, json_extract(c.declared,'$.ocr.text') AS ocr FROM captures c JOIN capture_sources cs "
                   "ON cs.capture_id=c.id WHERE cs.source_id=? LIMIT 3", (src["id"],))
    texts = [t for c in caps for t in (c["text"], c["ocr"]) if t]
    body = "\n".join(texts)[:1500]
    return f"Título: {src.get('title') or ''}\nURL: {src.get('url') or ''}\nRepo: {src.get('repo') or ''}\nTexto:\n{body}"


def run(store: Store, chat: ChatFn, *, channel: str = "", limit: int = 50,
        on_progress: Optional[Callable[[int, int], None]] = None) -> dict[str, Any]:
    cat = catalogue(store)
    todo = pending(store, channel=channel, limit=limit)
    proposed, skipped, noise = [], 0, 0
    for i, src in enumerate(todo):
        if on_progress:
            on_progress(i, len(todo))
        material = _material(store, src)
        near = tree.find(store, f"{src.get('title') or ''} {material[:600]}", limit=6).get("apps", [])
        near_ids = [a["app_id"] for a in near if a["app_id"] in cat]
        listing = "\n".join(f"- {k}: {v}" for k, v in cat.items())
        cov = coverage.classify(store, source_id=src["id"])
        covered_by = {a["app_id"]: a for a in cov["apps"] if cov["verdict"] == "covered" and a["strong_evidence"]
                      and a["matched_groups"] >= max(3, -(-a["of"] // 2))}
        cov_line = ("; ".join(f"{k} ya tiene {', '.join(n['name'] for n in v['nodes'][:3])}" for k, v in covered_by.items())
                    or "ninguna app lo cubre ya según el árbol")
        res = chat([{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"CATÁLOGO:\n{listing}\n\nApps cuyas capacidades comparten palabras: "
                                                f"{', '.join(near_ids) or 'ninguna'}\nCobertura: {cov_line}. No propongas para una app "
                                                f"algo que ya hace salvo que aporte algo nuevo concreto.\n\nDESCUBRIMIENTO:\n{material}"}],
                   json=SCHEMA, effort="low", max_tokens=300, temperature=0.1, timeout=90.0)
        if not res.get("ok"):
            return {"proposed": proposed, "skipped": skipped, "noise": noise, "remaining": len(todo) - i,
                    "error": f"{res.get('error')}: {res.get('detail') or ''}"}
        data = res.get("json") if isinstance(res.get("json"), dict) else {}
        app = data.get("app") if data.get("app") in cat else None
        verdict = {"at": time.time(), "app": app, "reason": str(data.get("reason") or "")[:300],
                   "useful": bool(data.get("useful", app is not None)), "model": res.get("model"),
                   "coverage": {"verdict": cov["verdict"], "apps": [a["app_id"] for a in cov["apps"][:3]]}}
        if app and app in covered_by:
            # the tree already answers it for that app: the proposal stays, flagged, for a person to check
            verdict["already_covered"] = [n["key"] for n in covered_by[app]["nodes"][:3]]
            verdict["reason"] = f"Posiblemente ya cubierto en {app}: {verdict['reason']}"[:300]
        meta = dict(src.get("meta") or {})
        meta["triage"] = verdict
        with store.tx() as c:
            c.execute("UPDATE sources SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), src["id"]))
        if app and verdict["useful"]:
            store.upsert_proposal(key=f"{src['key']}->{app}", source_id=src["id"], target=app, state="pendiente",
                                  origin="agent", reason=verdict["reason"], by="agent",
                                  declared={"triage_model": res.get("model"), **({"already_covered": verdict["already_covered"]}
                                                                                 if verdict.get("already_covered") else {})})
            proposed.append({"source_id": src["id"], "title": src.get("title"), "app": app, "reason": verdict["reason"]})
        elif not verdict["useful"]:
            noise += 1
        else:
            skipped += 1
    if on_progress:
        on_progress(len(todo), len(todo))
    return {"proposed": proposed, "skipped": skipped, "noise": noise, "remaining": 0}
