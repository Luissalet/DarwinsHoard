"""How worth a look an open discovery is (``fitness``, 0-100, with the reasons).

Only open discoveries are scored (no proposal yet, pending, being researched or debated, accepted, postponed): an
integrated, covered or discarded one has already been decided and scores 0. The score adds up what can be read from
Darwin's own data, each part with its reason so the number can be argued with:

* it matches an open gap (words of the gap in its title, summary or captured text): up to 30;
* it keeps coming back (appearances in radars, chats, posts): up to 20;
* GitHub stars: up to 15;
* a permissive licence (MIT, Apache, BSD, ISC, MPL, Unlicense): 10;
* it is recent (seen in the last 14 days: 15; 60 days: 8);
* it is a concrete repository rather than a post or a page: 10.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Optional

from .store import Store
from .tree import ALIASES, STOPWORDS, folded

OPEN = {"sin_propuesta", "pendiente", "investigando", "debatida", "aceptada", "aplazada", "en_marcha", "mixta", "parcial"}
PERMISSIVE = re.compile(r"\b(mit|apache|bsd|isc|mpl|unlicense|0bsd|zlib)\b", re.I)


def stars_of(value: Any) -> int:
    text = str(value or "").strip().lower().replace(",", "")
    m = re.match(r"([\d.]+)\s*([km]?)", text)
    if not m:
        return 0
    n = float(m.group(1))
    return int(n * (1000 if m.group(2) == "k" else 1_000_000 if m.group(2) == "m" else 1))


def gap_terms(store: Store) -> list[dict[str, Any]]:
    out = []
    for g in store.q("SELECT id, title, detail, target FROM gaps WHERE state='abierta'"):
        words = {w for w in re.findall(r"[a-z0-9]+", folded(f"{g['title']} {g['detail'] or ''}")) if len(w) >= 4 and w not in STOPWORDS}
        for w in list(words):
            words.update(ALIASES.get(w, "").split())
        if words:
            out.append({"id": g["id"], "title": g["title"], "target": g["target"], "words": words})
    return out


def score(source: dict[str, Any], aggregate: str, *, text: str = "", gaps: Optional[list[dict[str, Any]]] = None,
          now: Optional[float] = None) -> dict[str, Any]:
    if aggregate not in OPEN:
        return {"score": 0, "reasons": [f"ya decidido ({aggregate})"]}
    now = now or time.time()
    reasons: list[str] = []
    total = 0.0
    hay = set(re.findall(r"[a-z0-9]+", folded(f"{source.get('title') or ''} {source.get('summary') or ''} {source.get('repo') or ''} {text}")))
    best = None
    for g in gaps or []:
        hit = len(g["words"] & hay)
        if hit >= 2 and (best is None or hit > best[0]):
            best = (hit, g)
    if best:
        pts = min(30, 10 * best[0])
        total += pts
        reasons.append(f"encaja con la carencia «{best[1]['title']}» (+{pts})")
    caps = int(source.get("captures") or 0)
    if caps > 1:
        pts = min(20, round(8 * math.log2(caps)))
        total += pts
        reasons.append(f"aparece {caps} veces (+{pts})")
    stars = stars_of(source.get("stars"))
    if stars:
        pts = min(15, round(3 * math.log10(max(stars, 1))))
        total += pts
        reasons.append(f"{source.get('stars')} estrellas (+{pts})")
    if PERMISSIVE.search(str(source.get("license") or "")):
        total += 10
        reasons.append(f"licencia {source.get('license')} (+10)")
    age = now - float(source.get("last_seen") or 0)
    if age < 14 * 86400:
        total += 15
        reasons.append("visto en las dos últimas semanas (+15)")
    elif age < 60 * 86400:
        total += 8
        reasons.append("visto en los dos últimos meses (+8)")
    if (source.get("key") or "").startswith("repo:"):
        total += 10
        reasons.append("es un repositorio concreto (+10)")
    return {"score": int(min(100, round(total))), "reasons": reasons, "gap": best[1]["id"] if best else None}


def texts_by_source(store: Store, ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        if not part:
            continue
        rows = store.q("SELECT cs.source_id AS sid, c.text, json_extract(c.declared,'$.ocr.text') AS ocr FROM capture_sources cs "
                       f"JOIN captures c ON c.id=cs.capture_id WHERE cs.source_id IN ({','.join('?' * len(part))})", part)
        for r in rows:
            out[r["sid"]] = (out.get(r["sid"], "") + " " + (r["text"] or "") + " " + (r["ocr"] or ""))[:4000]
    return out
