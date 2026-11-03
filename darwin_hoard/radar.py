"""The gap-driven radar (``darwin_radar_plan`` / ``darwin_radar_run``): what to look for next, and looking for it.

``plan`` ranks the open gaps by how much a search would help and writes, for each, the searches to run (a GitHub query
in English built from the gap's words and the tree's aliases, and a web query), the discoveries Darwin already holds
that may answer it and whether the tree may already cover it. A scheduled task calls it, runs the searches, and records
what it finds with ``darwin_add``; ``run`` does the GitHub part itself and can register the new repositories.

Priority (0-100), each part with its reason: never searched +25; searched more than 30 days ago +10, in the last 7 days
-25; open more than 30 days +10; it names an app +5; candidates already in Darwin -8 each (up to -24: review them
first); the tree may already cover it -30. ``notify`` is false when nothing changed since the previous plan and no new
repository came up, so a schedule stays quiet when there is nothing useful to say."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Optional

from . import coverage
from .canon import source_key
from .store import OPEN_GAP_SQL, Store
from .tree import ALIASES, folded

SearchFn = Callable[[str, int], list[dict[str, Any]]]
SPANISH_HINTS = {"de", "la", "el", "los", "las", "una", "por", "con", "sin", "del", "para", "que"}


def english_terms(text: str, limit: int = 4) -> list[str]:
    """Words for a GitHub search: Spanish words become their alias translations; untranslated Spanish words are dropped."""
    out: list[str] = []
    for w in coverage.terms_of(text, max_terms=8):
        alias = ALIASES.get(w, "").split()
        picks = alias[:1] if alias else ([w] if w.isascii() and not _looks_spanish(w) else [])
        for p in picks:
            if p not in out:
                out.append(p)
    return out[:limit]


def _looks_spanish(word: str) -> bool:
    return word.endswith(("cion", "ciones", "mente", "ando", "iendo", "ado", "ada", "ados", "adas", "idad")) or word in SPANISH_HINTS


def queries_for(gap: dict[str, Any], keywords: str = "") -> dict[str, str]:
    """``keywords``: English keywords written by the local model (cached per gap); otherwise the tree's aliases."""
    text = f"{gap['title']} {gap.get('detail') or ''}"
    gh = " ".join(keywords.split()[:4]) if keywords else " ".join((english_terms(text) or coverage.terms_of(gap["title"], max_terms=3))[:3])
    web = f"{keywords} open source" if keywords else f"{gap['title']} open source"
    return {"github": f"{gh} in:name,description,readme" if gh else "", "web": web,
            "source": "model" if keywords else "aliases"}


TRANSLATE_SYSTEM = ("Para cada carencia (algo que se quiere hacer y ninguna app hace), escribe de 2 a 4 palabras clave en inglés, en "
                    "minúsculas, para buscar repositorios en GitHub que lo resuelvan: términos técnicos concretos, sin palabras vacías. "
                    "Devuelve JSON {items: [{id, keywords}]}.")
TRANSLATE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "integer"}, "keywords": {"type": "string"}}, "required": ["id", "keywords"]}}}, "required": ["items"]}


def translate_with(chat: Callable[..., dict[str, Any]], gaps: list[dict[str, Any]]) -> dict[int, str]:
    """One call to the family's local model for every gap without cached keywords; {} when no model answers."""
    lines = "\n".join(f"{g['id']}: {g['title']}" + (f" — {(g.get('detail') or '')[:200]}" if g.get("detail") else "") for g in gaps[:40])
    res = chat([{"role": "system", "content": TRANSLATE_SYSTEM}, {"role": "user", "content": lines}],
               json=TRANSLATE_SCHEMA, effort="low", max_tokens=1200, temperature=0.1, timeout=90.0)
    if not res.get("ok") or not isinstance(res.get("json"), dict):
        return {}
    out = {}
    for it in res["json"].get("items") or []:
        try:
            kw = " ".join(str(it.get("keywords") or "").lower().replace(",", " ").split()[:4])
            if kw:
                out[int(it["id"])] = kw
        except (TypeError, ValueError):
            continue
    return out


def _gap_hash(g: dict[str, Any]) -> str:
    return hashlib.sha1(f"{g['title']}\n{g.get('detail') or ''}".encode("utf-8")).hexdigest()[:12]


def keywords_for(store: Store, gaps: list[dict[str, Any]], translate: Optional[Callable[[list[dict[str, Any]]], dict[int, str]]]) -> dict[int, str]:
    cache = store.get_meta("radar_keywords", {}) or {}
    missing = [g for g in gaps if (cache.get(str(g["id"])) or {}).get("h") != _gap_hash(g)]
    if missing and translate:
        try:
            got = translate(missing)
        except Exception:  # noqa: BLE001 - no model: the aliases do
            got = {}
        for g in missing:
            if g["id"] in got:
                cache[str(g["id"])] = {"h": _gap_hash(g), "keywords": got[g["id"]]}
        if got:
            store.set_meta("radar_keywords", cache)
    return {g["id"]: cache[str(g["id"])]["keywords"] for g in gaps if (cache.get(str(g["id"])) or {}).get("h") == _gap_hash(g)}


def _candidates(store: Store, gaps: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Open discoveries sharing two or more words with each gap, best first."""
    import re
    from . import fitness, query
    items = [i for i in query.find(store, limit=100000)["items"] if i["state"] in fitness.OPEN]
    texts = fitness.texts_by_source(store, [i["id"] for i in items])
    out: dict[int, list[dict[str, Any]]] = {}
    for it in items:
        hay = set(re.findall(r"[a-z0-9]+", folded(f"{it['title'] or ''} {it['summary'] or ''} {it['repo'] or ''} {texts.get(it['id'], '')}")))
        for g in gaps:
            hit = g["words"] & hay
            if len(hit) >= 2:
                out.setdefault(g["id"], []).append({"id": it["id"], "title": it["title"] or it["repo"], "state": it["state"],
                                                    "url": it["url"], "shared": sorted(hit)})
    for gid in out:
        out[gid].sort(key=lambda c: -len(c["shared"]))
    return out


def plan(store: Store, *, limit: int = 10, now: Optional[float] = None, remember: bool = True,
         translate: Optional[Callable[[list[dict[str, Any]]], dict[int, str]]] = None) -> dict[str, Any]:
    from . import fitness
    now = now or time.time()
    rows = store.q("SELECT id, title, detail, target, created, watch FROM gaps WHERE " + OPEN_GAP_SQL)
    keywords = keywords_for(store, rows, translate)
    words = {g["id"]: g["words"] for g in fitness.gap_terms(store)}
    cands = _candidates(store, [{"id": gid, "words": w} for gid, w in words.items()])
    searched = store.get_meta("radar_searched", {}) or {}
    ranked = []
    for g in rows:
        reasons, score = [], 50
        last = float(searched.get(str(g["id"]), 0) or 0)
        if not last:
            score += 25
            reasons.append("nunca buscada (+25)")
        elif now - last > 30 * 86400:
            score += 10
            reasons.append("última búsqueda hace más de un mes (+10)")
        elif now - last < 7 * 86400:
            score -= 25
            reasons.append("buscada esta semana (-25)")
        if now - float(g["created"] or now) > 30 * 86400:
            score += 10
            reasons.append("abierta hace más de un mes (+10)")
        if g["target"]:
            score += 5
            reasons.append(f"para {g['target']} (+5)")
        mine = cands.get(g["id"], [])
        if mine:
            pts = min(24, 8 * len(mine))
            score -= pts
            reasons.append(f"{len(mine)} candidatos ya en Darwin: revisarlos primero (-{pts})")
        cov = coverage.classify(store, text=f"{g['title']} {g['detail'] or ''}")
        if cov["verdict"] == "covered":
            score -= 30
            reasons.append(f"el árbol quizá ya lo cubre: {cov['apps'][0]['app_id']} (-30)")
        ranked.append({"gap_id": g["id"], "title": g["title"], "target": g["target"], "priority": max(0, min(100, score)),
                       "reasons": reasons, "queries": queries_for(g, keywords.get(g["id"], "")), "candidates": mine[:5], "coverage": cov["verdict"],
                       "coverage_apps": [a["app_id"] for a in cov["apps"][:3]], "last_searched": last or None})
    ranked.sort(key=lambda r: (-r["priority"], r["gap_id"]))
    fingerprint = {str(r["gap_id"]): sorted(c["id"] for c in r["candidates"]) for r in ranked}
    previous = store.get_meta("radar_plan_fingerprint", None)
    new_gaps = sorted(int(k) for k in fingerprint if previous is None or k not in previous)
    new_cands = sorted({c for k, ids in fingerprint.items() for c in ids if previous and k in previous and c not in previous[k]})
    notify = bool(new_gaps or new_cands)
    if remember:
        store.set_meta("radar_plan_fingerprint", fingerprint)
        store.set_meta("radar_planned_at", now)
    return {"generated": now, "open_gaps": len(rows), "gaps": ranked[:limit], "notify": notify,
            "novelty": {"new_gaps": new_gaps, "new_candidates": new_cands},
            "summary": _summary(ranked, new_gaps, new_cands, notify, first=previous is None)}


def _summary(ranked: list[dict[str, Any]], new_gaps: list[int], new_cands: list[int], notify: bool, *, first: bool = False) -> str:
    if not ranked:
        return "No hay carencias abiertas: nada que buscar."
    if not notify:
        return "Sin novedades útiles desde el último plan."
    top = ranked[0]
    head = f"{len(ranked)} carencias abiertas; la primera, «{top['title']}» (prioridad {top['priority']})."
    if first:
        return head + " Es el primer plan que guarda el radar."
    return head + f" {len(new_gaps)} carencias nuevas y {len(new_cands)} candidatos nuevos desde el último plan."


def github_search(query: str, per_page: int = 5, timeout: float = 20.0) -> list[dict[str, Any]]:
    """GitHub's public repository search, anonymous (ten searches a minute: enough for a radar run)."""
    import urllib.parse
    import urllib.request
    # best match, not most stars: sorting by stars brings the big link collections first
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": query, "per_page": min(50, per_page * 3)})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "darwins-hoard"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:  # noqa: S310 - fixed host
        data = json.loads(resp.read().decode("utf-8"))
    out = [{"full_name": r.get("full_name"), "url": r.get("html_url"), "description": r.get("description") or "",
            "stars": r.get("stargazers_count") or 0, "license": ((r.get("license") or {}).get("spdx_id") or ""),
            "github_id": r.get("id"), "pushed_at": r.get("pushed_at")}
           for r in data.get("items") or [] if r.get("full_name") and not is_collection(r)]
    return out[:per_page]


def is_collection(repo: dict[str, Any]) -> bool:
    """A list of links (awesome-*, «curated list», «best websites») rather than a project that does something."""
    name = str(repo.get("name") or repo.get("full_name") or "").lower().split("/")[-1]
    desc = str(repo.get("description") or "").lower()
    topics = {str(t).lower() for t in repo.get("topics") or []}
    return (name.startswith("awesome") or "awesome-list" in topics or "awesome" in topics
            or any(p in desc for p in ("curated list", "a list of", "collection of awesome", "best websites")))


def run(store: Store, *, top: int = 3, per_gap: int = 5, add: bool = False, gap_ids: Optional[list[int]] = None,
        search: Optional[SearchFn] = None, now: Optional[float] = None,
        translate: Optional[Callable[[list[dict[str, Any]]], dict[int, str]]] = None) -> dict[str, Any]:
    """Search GitHub for the ``top`` gaps of the plan (or ``gap_ids``); report each repository as known or new and, with
    ``add``, register the new ones as discoveries (channel radar, linked to the gap they answer)."""
    now = now or time.time()
    search = search or github_search
    p = plan(store, limit=1000, now=now, remember=False, translate=translate)
    chosen = [g for g in p["gaps"] if g["gap_id"] in set(gap_ids)] if gap_ids else [g for g in p["gaps"] if g["queries"]["github"]][:top]
    searched = store.get_meta("radar_searched", {}) or {}
    results, new_total, errors = [], 0, []
    for g in chosen:
        q = g["queries"]["github"]
        if not q:
            continue
        try:
            repos = search(q, per_gap)
        except Exception as exc:  # noqa: BLE001 - one failed search (rate limit, offline) does not stop the run
            errors.append({"gap_id": g["gap_id"], "error": str(exc)[:200]})
            continue
        searched[str(g["gap_id"])] = now
        found = []
        for r in repos:
            key = source_key(repo=r["full_name"])
            known = store.source_by_key(key)
            item = {**r, "known": bool(known), "source_id": known["id"] if known else None}
            if not known:
                new_total += 1
                if add:
                    item["source_id"] = _register(store, r, g, now)
            found.append(item)
        results.append({"gap_id": g["gap_id"], "title": g["title"], "query": q, "repos": found})
    store.set_meta("radar_searched", searched)
    runs = (store.get_meta("radar_runs", []) or [])[-29:]
    runs.append({"at": now, "gaps": [r["gap_id"] for r in results], "new": new_total, "added": add, "errors": len(errors)})
    store.set_meta("radar_runs", runs)
    return {"at": now, "searched": len(results), "new": new_total, "added": new_total if add else 0, "notify": bool(new_total),
            "results": results, "errors": errors,
            "summary": (f"{new_total} repositorios nuevos en {len(results)} carencias." if new_total else "Sin repositorios nuevos.")}


def _register(store: Store, repo: dict[str, Any], gap: dict[str, Any], now: float) -> int:
    sid = store.upsert_source(url=repo["url"], repo=repo["full_name"], title=repo["full_name"], summary=repo["description"][:600],
                              license=repo["license"], stars=str(repo["stars"]), github_id=repo.get("github_id"),
                              meta={"radar_gap": gap["gap_id"]})
    digest = hashlib.sha1(f"{gap['gap_id']}:{repo['full_name']}".encode()).hexdigest()[:16]
    cid, _ = store.add_capture(capture_key=f"radar:gap:{digest}", channel="radar", text=f"{repo['url']}\n{repo['description']}",
                               url=repo["url"], author="radar",
                               declared={"gap": gap["gap_id"], "gap_title": gap["title"], "query": gap["queries"]["github"]},
                               provenance={"via": "darwin_radar_run", "gap": gap["gap_id"], "at": now})
    store.link_capture(cid, sid)
    return sid
