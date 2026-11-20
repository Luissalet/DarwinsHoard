"""Social posts behind discoveries: read them with the session the account holder signed in to, and link what they point at.

A discovery that is a post (``x.com/<user>/status/<id>``, an Instagram post or reel, a Threads post…) says little by its URL:
the repository or article is inside the text. Links reads the post with the browser profile where the account holder signed in
(``read_post``; ``site_login`` opens the sign-in window, and nobody but him types the password). The text becomes a capture
of the post (channel ``post``), the post's own source gets a readable title and summary, and the repositories and links in
it become sources linked to that capture: GitHub repositories and any non-social link as they are, bare ``owner/name``
only when GitHub confirms it. A login wall stops the run and names the site to connect.

A post that is a video (an Instagram reel, a TikTok) says even less in its caption: Links' ``video_digest`` watches it on the PC, and
Darwin keeps the digest's card as the source's summary (the caption stays in ``meta.video_digest.caption``) and takes the
repositories and links it names, with the same checks as the post's text. Every pass digests the reels it has read and not
digested yet, a few at a time because a digest takes minutes."""

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
VIDEO_PATTERNS = (r"^url:https://instagram\.com/(reel|reels|tv)/", r"^url:https://tiktok\.com/@[^/]+/video/")
DIGEST_PER_PASS = 2          # digests take minutes: the rest wait for the next pass
DIGEST_WAIT_S = 240          # how long one call waits for Links; a longer digest is found done by the next pass
DIGEST_ATTEMPTS = 2
DIGEST_CHARS = 1500          # what stays as the source's summary


def site_of(url: str) -> Optional[str]:
    host = re.sub(r"^https?://(www\.|mobile\.)?", "", url or "").split("/")[0].lower()
    return {"x.com": "x", "twitter.com": "x", "instagram.com": "instagram", "threads.net": "threads", "tiktok.com": "tiktok",
            "reddit.com": "reddit", "facebook.com": "facebook"}.get(host)


def is_post(key: str) -> bool:
    return any(re.match(p, key or "") for p in POST_PATTERNS)


def is_video(key: str) -> bool:
    return any(re.match(p, key or "") for p in VIDEO_PATTERNS)


def pending_digests(store: Store, limit: int = DIGEST_PER_PASS) -> list[dict[str, Any]]:
    """Video posts already read whose video was never digested (or whose digest failed fewer than DIGEST_ATTEMPTS times)."""
    rows = store.q("SELECT * FROM sources WHERE key LIKE 'url:%' AND json_extract(meta,'$.post') IS NOT NULL "
                   "AND json_extract(meta,'$.post.error') IS NULL ORDER BY last_seen DESC")
    out = []
    for r in rows:
        done = (r.get("meta") or {}).get("video_digest") or {}
        if is_video(r["key"]) and done.get("status") not in ("done", "partial") and int(done.get("attempts") or 0) < DIGEST_ATTEMPTS:
            out.append(r)
    return out[:limit]


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


def digest_video(store: Store, call: Call, src: dict[str, Any], *, repo_check: Callable[[str], Optional[bool]] = github_repo_exists,
                 cache: Optional[dict[str, Optional[bool]]] = None) -> dict[str, Any]:
    """Have Links watch the video of one post (``video_digest``, card level) and keep what it says: the card becomes the source's
    summary (the caption it replaces is kept in ``meta.video_digest.caption``) and the repositories and links the video names
    become sources linked to a capture of the digest. Returns ``{"status", "refs"}`` or ``{"error"}``; an unreachable Links
    is reported as ``{"error", "down": True}`` so the run stops."""
    res = call("links", "video_digest", {"url": src["url"], "level": "card", "wait": True, "timeout_s": DIGEST_WAIT_S, "max_chars": 8000},
               timeout=DIGEST_WAIT_S + 60.0)
    body = res.get("result") if isinstance(res.get("result"), dict) else {}
    if not res.get("ok") or not body:
        err = str(res.get("error") or body.get("error") or "Links did not answer")
        return {"error": err, "down": "not reachable" in err or res.get("status") in (502, 503)}
    status = str(body.get("status") or "")
    prior = ((src.get("meta") or {}).get("video_digest") or {})
    still = status in ("queued", "running")        # Links goes on in the background: the next pass finds it done, no attempt lost
    record: dict[str, Any] = {"at": time.time(), "status": status, "attempts": int(prior.get("attempts") or 0) + (0 if still else 1)}
    text = str(body.get("text") or "").strip()
    if status not in ("done", "partial") or not text:
        record["error"] = str(body.get("error") or body.get("detail") or f"the digest is {status or 'empty'}")[:300]
        if body.get("login"):
            record["login"] = body["login"]
        _set_meta(store, src, "video_digest", record)
        return {"status": status, "error": record["error"]}
    cid, _ = store.add_capture(capture_key="digest:" + hashlib.sha256((src["key"] + "\n" + text).encode("utf-8")).hexdigest()[:24],
                               channel="post", text=text[:8000], url=src["url"], at=time.time(), author="links",
                               provenance={"read_by": "links.video_digest", "source_key": src["key"], "link_id": body.get("link_id")})
    store.link_capture(cid, src["id"])
    cache = {} if cache is None else cache
    accepted: list[str] = []
    checks = 0
    for ref in extract_refs(text):
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
    record.update(link_id=body.get("link_id"), refs=accepted, caption=(src.get("summary") or "")[:600])
    _set_meta(store, src, "video_digest", record, summary=re.sub(r"\s+", " ", text).strip()[:DIGEST_CHARS])
    return {"status": status, "refs": accepted}


def read_posts(store: Store, call: Call, *, limit: int = 30, repo_check: Callable[[str], Optional[bool]] = github_repo_exists,
               on_progress: Optional[Callable[[int, int], None]] = None, digest: bool = True,
               digest_limit: int = DIGEST_PER_PASS) -> dict[str, Any]:
    todo = pending(store, limit)
    read = linked = 0
    found: list[str] = []
    errors: list[dict[str, Any]] = []
    cache: dict[str, Optional[bool]] = {}
    blocked: list[str] = []          # sites that asked for a sign-in in this pass: their posts wait, the others are read
    skipped = 0
    for i, src in enumerate(todo):
        if on_progress:
            on_progress(i, len(todo))
        if site_of(src["url"]) in blocked:
            skipped += 1
            continue
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
                blocked.append(site_of(src["url"]) or site or "?")
                skipped += 1
                continue
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
    digested = 0
    if digest:
        for src in pending_digests(store, digest_limit):
            got = digest_video(store, call, store.source(src["id"]) or src, repo_check=repo_check, cache=cache)
            if got.get("error"):
                errors.append({"source_id": src["id"], "error": got["error"][:200]})
                if got.get("down"):
                    break
                continue
            digested += 1
            found.extend(got.get("refs") or [])
            linked += 1 if got.get("refs") else 0
    if on_progress:
        on_progress(len(todo), len(todo))
    out: dict[str, Any] = {"read": read, "linked": linked, "found": found, "errors": errors, "remaining": skipped, "digested": digested}
    if blocked:
        sites = ", ".join(dict.fromkeys(blocked))
        out.update(login_needed=blocked[0], login_needed_sites=list(dict.fromkeys(blocked)),
                   error=f"Hace falta iniciar sesión en {sites} (Cuentas); el resto se ha leído.")
    return out
