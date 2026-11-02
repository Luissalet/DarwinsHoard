"""Social posts behind discoveries: read them with the session Luis signed in to, and link what they point at.

A discovery that is a post (``x.com/<user>/status/<id>``, an Instagram post or reel, a Threads post…) says little by its URL:
the repository or article is inside the text. Links reads the post with the browser profile where Luis signed in himself
(``read_post``; ``site_login`` opens the sign-in window, and nobody but him types the password). The text becomes a capture
of the post (channel ``post``), the post's own source gets a readable title and summary, and the repositories and links in
it become sources linked to that capture: GitHub repositories and any non-social link as they are, bare ``owner/name``
only when GitHub confirms it. A login wall stops the run and names the site to connect."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Optional

from .canon import extract_refs
from .ocr import MAX_CANDIDATES, github_repo_exists
from .store import Store

Call = Callable[..., dict[str, Any]]
POST_PATTERNS = (r"^url:https://x\.com/[^/]+/status/\d+", r"^url:https://instagram\.com/(p|reel|reels|tv)/", r"^url:https://threads\.net/@[^/]+/post/",
                 r"^url:https://tiktok\.com/@[^/]+/video/", r"^url:https://reddit\.com/r/[^/]+/comments/", r"^url:https://bsky\.app/profile/[^/]+/post/",
                 r"^url:https://linkedin\.com/(posts|feed/update)/")
SOCIAL = re.compile(r"^https?://([a-z0-9-]+\.)?(x|twitter|instagram|threads|facebook|tiktok|reddit|bsky|linkedin)\.(com|net|app)/", re.I)
SITES = ("x", "instagram", "threads", "tiktok", "reddit", "facebook")


def site_of(url: str) -> Optional[str]:
    host = re.sub(r"^https?://(www\.|mobile\.)?", "", url or "").split("/")[0].lower()
    return {"x.com": "x", "twitter.com": "x", "instagram.com": "instagram", "threads.net": "threads", "tiktok.com": "tiktok",
            "reddit.com": "reddit", "facebook.com": "facebook"}.get(host)


def is_post(key: str) -> bool:
    return any(re.match(p, key or "") for p in POST_PATTERNS)


def pending(store: Store, limit: int = 30) -> list[dict[str, Any]]:
    rows = store.q("SELECT * FROM sources WHERE key LIKE 'url:%' AND (json_extract(meta,'$.post') IS NULL "
                   "OR json_extract(meta,'$.post.error') IS NOT NULL) ORDER BY last_seen DESC")
    return [r for r in rows if is_post(r["key"])][:limit]


def _set_meta(store: Store, source: dict[str, Any], key: str, value: Any, **fields: Any) -> None:
    meta = dict(source.get("meta") or {})
    meta[key] = value
    sets = {"meta": json.dumps(meta, ensure_ascii=False), "updated": time.time(), **fields}
    with store.tx() as c:
        c.execute(f"UPDATE sources SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), source["id"]))


def read_posts(store: Store, call: Call, *, limit: int = 30, repo_check: Callable[[str], Optional[bool]] = github_repo_exists,
               on_progress: Optional[Callable[[int, int], None]] = None) -> dict[str, Any]:
    todo = pending(store, limit)
    read = linked = 0
    found: list[str] = []
    errors: list[dict[str, Any]] = []
    cache: dict[str, Optional[bool]] = {}
    for i, src in enumerate(todo):
        if on_progress:
            on_progress(i, len(todo))
        res = call("links", "read_post", {"url": src["url"]}, timeout=90.0)
        body = res.get("result") if isinstance(res.get("result"), dict) else {}
        if not res.get("ok") or not body:
            err = res.get("error") or body.get("error") or "Links did not answer"
            code = (res.get("result") or {}).get("code") if isinstance(res.get("result"), dict) else None
            text = json.dumps(res, ensure_ascii=False)
            refused = (any(w in text for w in ("LOGIN_NEEDED", "REFUSED", "iniciar sesión", "no dejó leer"))
                       or code in ("LOGIN_NEEDED", "REFUSED") or res.get("status") in (401, 403, 502))
            if refused:
                site = next((s for s in SITES if f'"{s}"' in text), None) or site_of(src["url"])
                return {"read": read, "linked": linked, "found": found, "errors": errors, "remaining": len(todo) - i,
                        "login_needed": site or "?", "error": f"Hace falta iniciar sesión en {site or 'el sitio'} (Cuentas)."}
            if "not reachable" in str(err) or res.get("status") in (502, 503):
                return {"read": read, "linked": linked, "found": found, "errors": errors, "remaining": len(todo) - i, "error": str(err)}
            _set_meta(store, src, "post", {"at": time.time(), "error": str(err)[:300]})
            errors.append({"source_id": src["id"], "error": str(err)[:200]})
            continue
        text = str(body.get("text") or "")
        links = body.get("links") or []
        joined = "\n".join([text, str(body.get("card") or ""), *[str(l.get("href") or "") for l in links]])
        cap_key = "post:" + hashlib.sha256((src["key"] + "\n" + text).encode("utf-8")).hexdigest()[:24]
        cid, _ = store.add_capture(capture_key=cap_key, channel="post", text=text[:8000], url=src["url"], at=time.time(),
                                   author=str(body.get("author") or "")[:200],
                                   provenance={"read_by": "links.read_post", "site": body.get("site"), "source_key": src["key"]})
        store.link_capture(cid, src["id"])
        accepted: list[str] = []
        checks = 0
        for ref in extract_refs(joined):
            if ref["kind"] == "candidate":
                repo = ref["raw"]
                if repo not in cache:
                    if checks >= MAX_CANDIDATES:
                        continue
                    checks += 1
                    cache[repo] = repo_check(repo)
                if not cache[repo]:
                    continue
                sid = store.upsert_source(repo=repo)
            else:
                if SOCIAL.match(ref["url"]) or ref["key"] == src["key"]:
                    continue
                sid = store.upsert_source(url=ref["url"])
            store.link_capture(cid, sid)
            accepted.append(ref["url"])
        author = str(body.get("author") or "").split("·")[0].strip()
        first = re.sub(r"\s+", " ", text).strip()[:90]
        title_fields = {}
        if (src.get("title") or "") in ("", src.get("url"), src["key"][4:]) and (first or author):
            title_fields["title"] = f"{author}: {first}" if author and first else (first or author)
        if not src.get("summary") and text:
            title_fields["summary"] = re.sub(r"\s+", " ", text).strip()[:600]
        _set_meta(store, src, "post", {"at": time.time(), "site": body.get("site"), "author": author, "refs": accepted}, **title_fields)
        read += 1
        linked += 1 if accepted else 0
        found.extend(accepted)
    if on_progress:
        on_progress(len(todo), len(todo))
    return {"read": read, "linked": linked, "found": found, "errors": errors, "remaining": 0}
