"""Links saved in Links' Hoard that are meant for Darwin (``darwin_import_links``).

Links keeps everything Luis saves to read later, mostly videos he downloads; only two kinds are discoveries: a link he
tags ``darwin`` and any GitHub repository. Each becomes a capture (channel ``links``, keyed by the Links id, so importing
again adds nothing) of the source its URL names; the saved title and excerpt fill a source that has none yet. Only the
URL is read for identity: words of a title never become a guessed ``owner/name``."""

from __future__ import annotations

import time
from typing import Any, Callable

from .canon import canonical_url, source_key
from .store import Store

Call = Callable[..., dict[str, Any]]
TAG = "darwin"


def _pages(call: Call, **filters: Any) -> list[dict[str, Any]]:
    items, cursor = [], 0
    for _ in range(50):
        res = call("links", "list_links", {"state": "all", "limit": 100, "cursor": cursor, **filters}, timeout=30.0)
        body = res.get("result") if isinstance(res.get("result"), dict) else None
        if not res.get("ok") or body is None:
            raise RuntimeError(res.get("error") or "Links did not answer")
        items += body.get("items") or []
        cursor = body.get("next_cursor")
        if not cursor:
            break
    return items


def import_links(store: Store, call: Call) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for item in _pages(call, tag=TAG) + _pages(call, site="github.com"):
        if item.get("id") and item.get("url"):
            seen[item["id"]] = item
    created = existing = 0
    sources: set[int] = set()
    for lid, item in seen.items():
        url = canonical_url(item["url"])
        try:
            key = source_key(url=url)
        except ValueError:
            continue
        if key.startswith("url:") and TAG not in (item.get("tags") or []):
            continue  # a github.com page that is not a repository (a profile, a search): only when tagged
        cid, was_new = store.add_capture(capture_key=f"links:{lid}", channel="links", text=url, url=url,
                                         at=time.time(), author="links",
                                         provenance={"links_id": lid, "saved_at": item.get("saved_at"), "tags": item.get("tags") or []},
                                         declared={"title": item.get("title") or "", "excerpt": (item.get("excerpt") or "")[:600],
                                                   "notes": (item.get("notes") or "")[:600]})
        sid = store.upsert_source(url=url, title=item.get("title") or "", summary=(item.get("excerpt") or "")[:600])
        store.link_capture(cid, sid)
        sources.add(sid)
        created += 1 if was_new else 0
        existing += 0 if was_new else 1
    return {"links_read": len(seen), "created": created, "existing": existing, "sources": len(sources)}
