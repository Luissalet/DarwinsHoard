"""Questions in plain words over the tree and the history (``darwin_ask``).

Retrieval first, in this process and without a model: which apps cover the words of the question (the capability tree),
which discoveries mention them (titles, repositories, summaries and the text of their captures, ranked by how many words
they share) and the open gaps. Then one call to the local model of the family (through the hub, so it costs nothing and
runs on the Sparks or the PC) writes the answer from that material only, citing what it used. Without a model the
retrieved material is still returned, so the question is never a dead end."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from . import query, tree
from .store import OPEN_GAP_SQL, Store

ChatFn = Callable[..., dict[str, Any]]

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "discoveries": {"type": "array", "items": {"type": "integer"}},
        "apps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer"],
}

SYSTEM = ("Eres Darwin, el archivo de descubrimientos de la familia Faustus/Hoards. Responde en castellano de España, directo y "
          "breve (máximo 8 frases o una lista corta). Usa SOLO el material que se te da: apps que ya cubren algo (árbol de "
          "capacidades), descubrimientos con su estado y app propuesta, y carencias abiertas. Si el material no basta, dilo. "
          "No inventes repos, apps ni estados. Cita los descubrimientos por su número [#id] y las apps por su id. "
          "Devuelve JSON: {answer, discoveries: [ids usados], apps: [app ids usados]}.")


def terms_of(question: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", tree.folded(question)) if w not in tree.STOPWORDS and len(w) >= 3]
    out: list[str] = []
    for w in words:
        for t in [w, *tree.ALIASES.get(w, "").split()]:
            if t not in out:
                out.append(t)
    return out[:14]


def discoveries_for(store: Store, terms: list[str], limit: int = 12) -> list[dict[str, Any]]:
    """Sources sharing the most words with the question (any word, ranked), with their aggregate state."""
    scores: dict[int, int] = {}
    for t in terms:
        like = f"%{t}%"
        rows = store.q(
            "SELECT DISTINCT s.id FROM sources s WHERE LOWER(COALESCE(s.title,'')) LIKE ? OR LOWER(COALESCE(s.repo,'')) LIKE ? "
            "OR LOWER(COALESCE(s.summary,'')) LIKE ? OR s.id IN (SELECT cs.source_id FROM capture_sources cs JOIN captures c "
            "ON c.id=cs.capture_id WHERE LOWER(c.text) LIKE ? OR LOWER(COALESCE(json_extract(c.declared,'$.ocr.text'),'')) LIKE ?)",
            (like, like, like, like, like))
        for r in rows:
            scores[r["id"]] = scores.get(r["id"], 0) + (2 if len(t) >= 5 else 1)
    best = sorted(scores, key=lambda i: -scores[i])[:limit]
    out = []
    for sid in best:
        g = query.genealogy(store, source_id=sid)
        if not g:
            continue
        src = g["source"]
        out.append({"id": sid, "title": src.get("title") or src.get("repo") or src.get("url"), "repo": src.get("repo"),
                    "url": src.get("url"), "state": g.get("state"),
                    "proposals": [{"app": p.get("target"), "state": p.get("state")} for p in (g.get("proposals") or [])][:6],
                    "summary": (src.get("summary") or "")[:240]})
    return out


def _material(apps: list[dict[str, Any]], found: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> str:
    lines = ["APPS QUE YA CUBREN ALGO (árbol):"]
    for a in apps[:6]:
        caps = ", ".join(m["name"] for m in a["matches"][:6])
        lines.append(f"- {a['app_id']} ({' > '.join(a.get('path') or [])}): {caps}")
    lines.append("DESCUBRIMIENTOS:")
    for d in found:
        props = "; ".join(f"{p['app'] or 'sin app'}={p['state']}" for p in d["proposals"]) or "sin propuesta"
        lines.append(f"- [#{d['id']}] {d['title']} · estado {d['state']} · {props}" + (f" · {d['summary']}" if d["summary"] else ""))
    if gaps:
        lines.append("CARENCIAS ABIERTAS:")
        lines += [f"- {g['title']}" + (f" (para {g['target']})" if g.get("target") else "") for g in gaps[:8]]
    return "\n".join(lines)


def ask(store: Store, question: str, chat: Optional[ChatFn] = None) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise ValueError("Write a question.")
    terms = terms_of(question)
    apps = tree.find(store, question, limit=6).get("apps", []) if terms else []
    found = discoveries_for(store, terms) if terms else []
    gap_rows = store.q("SELECT id, title, target FROM gaps WHERE " + OPEN_GAP_SQL)
    gaps = [g for g in gap_rows if any(t in tree.folded(g["title"]) for t in terms)]
    out: dict[str, Any] = {"question": question, "terms": terms, "apps": [{"app_id": a["app_id"], "path": a.get("path"),
                           "matches": [m["name"] for m in a["matches"][:6]]} for a in apps],
                           "discoveries": found, "gaps": gaps, "answer": None, "model": None}
    if chat is None:
        out["note"] = "No model was asked: this is what Darwin holds for those words."
        return out
    res = chat([{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Pregunta: {question}\n\nMaterial:\n{_material(apps, found, gaps)}"}],
               json=SCHEMA, effort="low", max_tokens=900, temperature=0.2, timeout=120.0)
    if not res.get("ok"):
        out["note"] = f"The local model did not answer ({res.get('error')}: {res.get('detail') or ''}); the material is below."
        return out
    data = res.get("json") if isinstance(res.get("json"), dict) else {}
    out["answer"] = (data.get("answer") or res.get("text") or "").strip()
    valid = {d["id"] for d in found}
    out["cited"] = [i for i in (data.get("discoveries") or []) if isinstance(i, int) and i in valid]
    out["model"] = res.get("model")
    return out
