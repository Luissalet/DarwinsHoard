"""Does the family already do this? (``darwin_coverage``): a discovery, an idea or a gap against the capability tree.

The distinctive words of the text (title, summary, repository name and what its captures say, with the Spanish-English
aliases of the tree) are matched against the NAME of capability and tool nodes, app by app: a node is called after what it
does, while its description is prose that mentions everything around it (a Blender tool that runs code is not a code
editor, a floorplan tool that reads a repository is not a repository manager). A word that names nodes in many apps says
nothing about any of them, so it is left out of the count. The verdict is one of:

* ``covered``: one app's capabilities or tools carry at least half of the words (three or more) and at least one of the
  matching nodes is live, tested or marked implemented with evidence;
* ``partial``: some app matches two or more words, but not enough, or only by its declared manifest;
* ``gap``: no app matches two words.

It explains, it never blocks: the matching nodes travel with the verdict so a person can check it in the tree."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from .backing import all_backing, is_backed
from .tree import ALIASES, STOPWORDS, folded

#: Words that say nothing about what a project does.
GENERIC = {"https", "http", "github", "com", "www", "repo", "repos", "repository", "project", "projects", "open", "source", "free",
           "with", "your", "this", "that", "from", "into", "using", "based", "tool", "tools", "app", "apps", "library", "simple",
           "fast", "best", "awesome", "built", "make", "made", "more", "less", "like", "just", "also", "other", "about", "than",
           "they", "them", "what", "when", "which", "where", "while", "will", "would", "could", "should", "have", "has", "been",
           "para", "como", "esta", "este", "esto", "todo", "todos", "pero", "porque", "sobre", "desde", "entre", "hacer", "puede",
           "mira", "aqui", "html", "readme", "main", "master", "tree", "blob", "issues", "pull", "status", "stars", "star", "fork"}
MAX_TERMS = 12

#: A word that names nodes in this many apps (or in this share of them) is furniture, not a subject: «code», «text»,
#: «read». It is reported with the verdict but it never counts towards covered or partial.
COMMON_APPS = 6
COMMON_SHARE = 0.15


def terms_of(text: str, max_terms: int = MAX_TERMS) -> list[str]:
    """The most frequent distinctive words of a text, each with its alias translations, most frequent first."""
    words = [w for w in re.findall(r"[a-z][a-z0-9]+", folded(text)) if len(w) >= 4 and w not in STOPWORDS and w not in GENERIC]
    out: list[str] = []
    for w, _ in Counter(words).most_common(max_terms):
        for t in [w, *ALIASES.get(w, "").split()]:
            if t and t not in out and t not in GENERIC:
                out.append(t)
    return out[: max_terms * 2]


def _node_terms(row: dict[str, Any]) -> set[str]:
    """The words of a node's name: what the capability or tool is called, not the prose of its description."""
    return set(re.findall(r"[a-z0-9]+", folded(row["name"] or "")))


def _reach(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many different apps have a node whose name carries each word."""
    apps: dict[str, set[str]] = {}
    for r in rows:
        for term in _node_terms(r):
            apps.setdefault(term, set()).add(r["app_id"])
    return {term: len(seen) for term, seen in apps.items()}


def _common(reach: dict[str, int], app_count: int) -> set[str]:
    """The words too widespread to say anything about one app."""
    limit = max(COMMON_APPS, int(app_count * COMMON_SHARE))
    return {term for term, n in reach.items() if n > limit}


def _text_of_source(store, source_id: int) -> tuple[Optional[dict[str, Any]], str]:
    from .fitness import texts_by_source
    src = store.source(source_id)
    if not src:
        return None, ""
    extra = texts_by_source(store, [source_id]).get(source_id, "")
    repo_words = re.sub(r"[/_.-]+", " ", src.get("repo") or "")
    return src, f"{src.get('title') or ''} {repo_words} {src.get('summary') or ''} {extra}"


def classify(store, *, source_id: Optional[int] = None, text: str = "", exclude_apps: tuple[str, ...] = ()) -> dict[str, Any]:
    """Verdict covered / partial / gap for a discovery (``source_id``) or a free text, with the apps and nodes that match."""
    src = None
    if source_id:
        src, text = _text_of_source(store, source_id)
        if src is None:
            raise KeyError(f"Discovery {source_id} does not exist.")
    terms = terms_of(text)
    out: dict[str, Any] = {"source_id": source_id, "terms": terms, "verdict": "gap", "apps": [], "reason": ""}
    if len(terms) < 2:
        out["reason"] = "Too few distinctive words to compare with the tree."
        out["verdict"] = "unknown"
        return out
    proofs = all_backing(store)
    rows = [r for r in store.q("SELECT key, level, name, app_id, detail, evidence, operation FROM capabilities "
                               "WHERE level IN ('capability','tool')") if r["app_id"] and r["app_id"] not in exclude_apps]
    reach = _reach(rows)
    common = _common(reach, len({r["app_id"] for r in rows}))
    per_app: dict[str, dict[str, Any]] = {}
    for r in rows:
        hit = _node_terms(r) & set(terms)
        if not hit:
            continue
        entry = per_app.setdefault(r["app_id"], {"app_id": r["app_id"], "terms": set(), "nodes": []})
        entry["terms"] |= hit
        backed = is_backed(proofs.get(r["key"]))
        entry["nodes"].append({"key": r["key"], "level": r["level"], "name": r["name"], "evidence": "probada" if backed else r["evidence"],
                               "backed": backed, "operation": r["operation"], "matched": sorted(hit),
                               "common": sorted(hit & common)})
    # words and their aliases count once: «voz» and «voice» are the same idea
    groups = _groups(terms)
    # a group only counts when at least one of its words is not furniture
    counted = [g for g in groups if g - common]
    ranked = []
    for e in per_app.values():
        covered_groups = sum(1 for g in counted if g & e["terms"])
        if not covered_groups:      # it only shares furniture words with the text: not a candidate
            continue
        strong = any(n["backed"] or n["evidence"] in ("viva", "probada") for n in e["nodes"])
        e["nodes"].sort(key=lambda n: (-len(n["matched"]), not n["backed"], n["level"] != "capability", n["name"]))
        ranked.append({"app_id": e["app_id"], "matched_groups": covered_groups, "of": len(counted), "terms": sorted(e["terms"]),
                       "strong_evidence": strong, "nodes": e["nodes"][:8]})
    ranked.sort(key=lambda a: (-a["matched_groups"], not a["strong_evidence"], a["app_id"]))
    out["apps"] = ranked[:6]
    out["common_terms"] = sorted(t for t in terms if t in common)
    best = ranked[0] if ranked else None
    if best and best["matched_groups"] >= max(3, -(-len(counted) // 2)) and best["strong_evidence"]:
        out["verdict"] = "covered"
        out["reason"] = f"{best['app_id']} matches {best['matched_groups']} of {len(counted)} ideas with live or tested nodes."
    elif best and best["matched_groups"] >= 2:
        out["verdict"] = "partial"
        out["reason"] = (f"{best['app_id']} matches {best['matched_groups']} of {len(counted)} ideas"
                         + ("" if best["strong_evidence"] else ", only by what its manifest declares") + ".")
    else:
        out["reason"] = "No app matches two of its ideas."
    return out


def _groups(terms: list[str]) -> list[set[str]]:
    """Each original word with its alias translations, as one group."""
    groups: list[set[str]] = []
    for t in terms:
        aliases = set(ALIASES.get(t, "").split())
        for g in groups:
            if t in g or g & aliases:
                g.add(t)
                g |= aliases
                break
        else:
            groups.append({t, *aliases})
    return groups
