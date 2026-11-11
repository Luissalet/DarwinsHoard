"""Gaps from the long running objective logs (Faustus's and Writer's ``OBJETIVOS.md``).

Those files are not lists: they are dated diaries of thousands of lines where what was delivered and what is still wanted
live in the same paragraphs. ``gaps.import_objectives`` skips a file that long as «a log»; this module reads it anyway,
in two steps:

1. **Candidates, without a model.** A section heading, a bullet or a sentence becomes a candidate only when it says that
   something is still open («falta», «sigue sin», «pendiente», «siguen pendientes», «queda», «no existe», «hoy solo»,
   «continuar»...), or when it is a bullet under a heading that is itself a to-do list («Lo siguiente», «siguientes
   pasos», «pendientes», «restante»). Sections older than ``days`` before the newest dated one are ignored.
2. **Sorting done from pending, with the family's local model** (as ``darwin_ask`` does). One call per ten candidates
   answers «still wanted and not done?» and writes a short title. Without a model the cue alone decides and the gap says
   so (``classified: heuristic``); when a model was asked and did not answer, the batch is left for the next run, so a
   dead model never fills the list with history.

Every gap keeps its origin in ``watch``: file, section, line, and a key made from the text itself (not from the line, which
moves). Idempotent: a candidate already imported is left alone, one the model rejected is remembered and not asked again,
and an open gap whose text left the file is closed, as with the plain lists."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .store import Store
from .tree import folded

ChatFn = Callable[..., dict[str, Any]]

FROM = "objetivos-log"
DEFAULT_DAYS = 21
MAX_CANDIDATES = 220
BATCH = 10
MAX_NEW_PER_RUN = 60
CLOSED = "cerrada"

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_BULLET = re.compile(r"^(?:[-*]|\d+[.)])\s+(.+)$")
_DATE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(20\d{2})\b")
_SECTION_TODO = re.compile(r"pendiente|siguientes? pasos?|siguiente trabajo|lo siguiente|restante|mejoras|ideas y ajustes|limites conocidos|"
                           r"trasladados desde pendientes", re.I)
_OPEN = re.compile(
    r"\b(falta(?:n)?|sigue(?:n)? (?:sin|pendientes?|abiert[oa]s?|fuera)|siguen? sin|quedan?|queda(?:n)? pendientes?|pendientes?|"
    r"todavia no|aun no|hoy (?:solo|no|queda)|no (?:hace|hacen|existe|existen|hay|tiene|tienen|admite|cubre|esta acreditad[oa]|"
    r"estan acreditad[oa]s|se hace|resuelve)|sin (?:comprobar|acreditar|probar|medir|cerrar|decidir)|por (?:hacer|probar|"
    r"comprobar|medir|implementar)|continuar|decidir|pendiente de)\b")
_DONE_START = re.compile(r"^(?:\W*)(?:hecho|integrad|entregad|resuelt|completad|cerrad|ya (?:esta|existe|funciona)|superad|probad)", re.I)
_NOISE = re.compile(r"^[\W_]*$|^\[[^\]]*\]\([^)]*\)\W*$")


def _fold(text: str) -> str:
    return folded(text)


def _key(text: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", _fold(text)).strip()[:400]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _clean(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", text)).strip()


def _title(text: str, bold: Optional[str] = None) -> str:
    if bold:
        return _clean(bold).rstrip(".:;")[:160]
    first = re.split(r"(?<=[.:;])\s|\s[—–]\s", text, maxsplit=1)[0]
    return _clean(first).rstrip(".:;")[:110]


def _section_date(heading: str) -> Optional[float]:
    m = _DATE.search(heading)
    if not m:
        return None
    try:
        return time.mktime((int(m.group(3)), int(m.group(2)), int(m.group(1)), 12, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return None


def _sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\[*`])", paragraph)
    return [p.strip() for p in parts if p.strip()]


def parse_log(text: str, *, days: int = DEFAULT_DAYS) -> list[dict[str, Any]]:
    """Candidates of an objective log, newest section first as the file has them: ``{title, detail, line, section,
    section_line, key, kind}``. Pure and model-free; the cue decides."""
    lines = text.splitlines()
    sections: list[dict[str, Any]] = []
    cur = {"title": "", "line": 1, "start": 0, "date": None, "todo": False}
    sections.append(cur)
    for i, raw in enumerate(lines):
        m = _HEADING.match(raw)
        if m and not raw.startswith("#" * 5):
            cur = {"title": _clean(m.group(2)), "line": i + 1, "start": i + 1, "date": _section_date(m.group(2)),
                   "todo": bool(_SECTION_TODO.search(_fold(m.group(2))))}
            sections.append(cur)
    newest = max((s["date"] for s in sections if s["date"]), default=None)
    cutoff = newest - days * 86400 if newest else None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    in_fence = False
    section_idx = 0
    para: list[str] = []
    para_line = 0
    bullet_indent_block = False

    def section_of(line_no: int) -> dict[str, Any]:
        nonlocal section_idx
        while section_idx + 1 < len(sections) and sections[section_idx + 1]["line"] <= line_no:
            section_idx += 1
        return sections[section_idx]

    def add(kind: str, body: str, line_no: int, bold: Optional[str] = None) -> None:
        sec = section_of(line_no)
        if cutoff and sec["date"] and sec["date"] < cutoff:
            return
        plain = _clean(body)
        if len(plain) < 25 or _NOISE.match(plain):
            return
        key = _key(plain)
        if key in seen:
            return
        seen.add(key)
        out.append({"title": _title(plain, bold), "detail": plain[:1200], "line": line_no, "section": sec["title"],
                    "section_line": sec["line"], "key": key, "kind": kind})

    def flush() -> None:
        nonlocal para, para_line
        if not para:
            return
        block = " ".join(para)
        sec = section_of(para_line)
        b = _BULLET.match(para[0])
        if b:
            body = " ".join([b.group(1), *[p.strip() for p in para[1:]]])
            folded_body = _fold(body)
            bold = re.match(r"\*\*(.+?)\*\*", body)
            has_cue = bool(_OPEN.search(folded_body))
            if has_cue or (sec["todo"] and not _DONE_START.match(_fold(body))):
                add("bullet", body, para_line, bold.group(1) if bold else None)
        else:
            if block.rstrip().endswith(":") and _SECTION_TODO.search(_fold(block)):
                sec["todo"] = True  # «Hecho y verificado. Lo siguiente:» introduces a to-do list
            for sent in _sentences(block):
                if _OPEN.search(_fold(sent)) and not _DONE_START.match(_fold(sent)):
                    add("sentence", sent, para_line)
        para, para_line = [], 0

    for i, raw in enumerate(lines):
        if raw.strip().startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip().startswith("|"):
            continue
        if _HEADING.match(raw):
            flush()
            continue
        if not raw.strip():
            flush()
            continue
        starts_bullet = bool(_BULLET.match(raw)) and not raw.startswith((" ", "\t"))
        if starts_bullet:
            flush()
            para, para_line = [raw.rstrip()], i + 1
        elif para:
            para.append(raw.strip())
        else:
            para, para_line = [raw.strip()], i + 1
    flush()
    return out[:MAX_CANDIDATES]


# ---------------------------------------------------------------------- the model

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "n": {"type": "integer"}, "open": {"type": "boolean"}, "title": {"type": "string"}}, "required": ["n", "open"]}}},
    "required": ["items"],
}

SYSTEM = ("Clasificas fragmentos de un fichero de objetivos de un proyecto de software. Para cada fragmento decide si expresa algo que "
          "se QUIERE hacer y AÚN NO está hecho (open=true), o si es historia, algo ya entregado, integrado o superado, contexto, "
          "un descarte explícito o una instrucción de método sin objetivo propio (open=false). Si mezcla lo hecho y lo pendiente, "
          "open=true solo cuando queda algo concreto sin hacer. En title escribe, en castellano de España y en máximo 100 "
          "caracteres, solo lo que falta (sin empezar por «Falta»). Devuelve JSON {items:[{n, open, title}]} con un elemento por "
          "fragmento y su número n.")


def classify(candidates: list[dict[str, Any]], chat: ChatFn) -> dict[str, Any]:
    """``{decisions: {key: {open, title}}, failed: [keys]}`` for the candidates, ten per model call."""
    decisions: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i + BATCH]
        body = "\n\n".join(f"[{n}] (sección: {c['section'][:80]})\n{c['detail'][:700]}" for n, c in enumerate(batch, 1))
        res = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Fragmentos:\n\n{body}"}],
                   json=SCHEMA, effort="low", max_tokens=1800, temperature=0.1, timeout=180.0)
        data = res.get("json") if res.get("ok") and isinstance(res.get("json"), dict) else None
        items = (data or {}).get("items")
        if not isinstance(items, list):
            failed.extend(c["key"] for c in batch)
            continue
        answered: set[int] = set()
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("n"), int) or not 1 <= it["n"] <= len(batch):
                continue
            answered.add(it["n"])
            title = _clean(str(it.get("title") or ""))[:160]
            decisions[batch[it["n"] - 1]["key"]] = {"open": bool(it.get("open")), "title": title}
        failed.extend(c["key"] for n, c in enumerate(batch, 1) if n not in answered)
    return {"decisions": decisions, "failed": failed}


# ---------------------------------------------------------------------- importing

def import_log(store: Store, path: Path, app: Optional[str], *, chat: Optional[ChatFn] = None, days: int = DEFAULT_DAYS,
               max_new: int = MAX_NEW_PER_RUN) -> dict[str, Any]:
    """Import one log. Returns the counts and what was left for later."""
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": str(exc)}
    cands = parse_log(text, days=days)
    keys = {c["key"] for c in cands}
    rows = store.q("SELECT id, state, watch FROM gaps WHERE json_extract(watch,'$.file')=? AND json_extract(watch,'$.from')=?", (source, FROM))
    existing: dict[str, dict[str, Any]] = {}
    for r in rows:
        w = r["watch"] if isinstance(r["watch"], dict) else json.loads(r["watch"] or "{}")
        existing[w.get("key", "")] = {"id": r["id"], "state": r["state"], "watch": w}
    meta_key = f"gaps_log_rejected:{source}"
    rejected = set(store.get_meta(meta_key, []) or [])
    fresh = [c for c in cands if c["key"] not in existing and c["key"] not in rejected]
    added = kept = closed = moved = 0
    pending = 0
    model_name = None
    if chat is not None and fresh:
        batch = fresh[:max_new]
        pending = len(fresh) - len(batch)
        verdict = classify(batch, chat)
        decisions, pending = verdict["decisions"], pending + len(verdict["failed"])
        rejected.update(k for k, d in decisions.items() if not d["open"])
        accepted = [(c, decisions[c["key"]]) for c in batch if c["key"] in decisions and decisions[c["key"]]["open"]]
        how = "model"
    else:
        accepted = [(c, {"title": ""}) for c in fresh[:max_new]]
        pending = max(0, len(fresh) - max_new)
        how = "heuristic"
    for c, d in accepted:
        store.add_gap(title=d.get("title") or c["title"], detail=c["detail"], target=app or "",
                      watch={"file": source, "from": FROM, "key": c["key"], "section": c["section"], "line": c["line"],
                             "section_line": c["section_line"], "classified": how})
        added += 1
    by_key = {c["key"]: c for c in cands}
    for key, ex in existing.items():
        c = by_key.get(key)
        if c:
            kept += 1
            w = ex["watch"]
            if w.get("line") != c["line"] or w.get("section") != c["section"]:
                w.update(line=c["line"], section=c["section"], section_line=c["section_line"])
                with store.tx() as con:
                    con.execute("UPDATE gaps SET watch=? WHERE id=?", (json.dumps(w, ensure_ascii=False), ex["id"]))
                moved += 1
        elif ex["state"] == "abierta":
            with store.tx() as con:
                con.execute("UPDATE gaps SET state=?, updated=? WHERE id=?", (CLOSED, time.time(), ex["id"]))
            closed += 1
    store.set_meta(meta_key, sorted(rejected)[:2000])
    return {"app": app, "candidates": len(cands), "added": added, "kept": kept, "closed": closed, "moved": moved,
            "rejected": len(rejected), "pending": pending, "classified": how}
