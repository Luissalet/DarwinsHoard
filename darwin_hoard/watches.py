"""Saved questions («avísame cuando…»): a question kept and asked again, which only speaks when the answer grows.

Each check runs the same local retrieval as ``darwin_ask`` (apps of the tree, discoveries, open gaps; no model) and
compares what it finds with the previous check: new discoveries or apps are the news. The first check sets the
baseline and says nothing; later checks list only what is new, and ``notify`` is false when nothing is. Darwin's loop
checks every saved question every few hours and sends a family notification for the ones with news."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from . import ask
from .store import Store, _j

STATES = ("activa", "pausada")


def _row(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    for k in ("seen", "last_news"):
        try:
            out[k] = json.loads(out[k]) if isinstance(out.get(k), str) and out[k] else out.get(k)
        except ValueError:
            out[k] = None
    return out


def add(store: Store, question: str, *, note: str = "", target: str = "") -> dict[str, Any]:
    question = question.strip()
    if len(question) < 3:
        raise ValueError("Write the question to keep.")
    now = time.time()
    existing = store.one("SELECT id FROM watches WHERE LOWER(question)=LOWER(?) AND state='activa'", (question,))
    if existing:
        return get(store, existing["id"])
    with store.tx() as c:
        wid = int(c.execute("INSERT INTO watches(question, note, target, created, updated) VALUES (?,?,?,?,?)",
                            (question, note, target or None, now, now)).lastrowid)
    check_one(store, wid, now=now)  # baseline: what exists today is not news
    return get(store, wid)


def get(store: Store, wid: int) -> dict[str, Any]:
    r = store.one("SELECT * FROM watches WHERE id=?", (wid,))
    if not r:
        raise KeyError(f"Saved question {wid} does not exist.")
    return _row(r)


def listing(store: Store) -> dict[str, Any]:
    rows = [_row(r) for r in store.q("SELECT * FROM watches ORDER BY state, COALESCE(last_news_at, 0) DESC, id DESC")]
    return {"watches": rows, "active": sum(1 for r in rows if r["state"] == "activa"),
            "with_news": sum(1 for r in rows if r.get("last_news"))}


def _snapshot(store: Store, question: str) -> dict[str, Any]:
    r = ask.ask(store, question, chat=None)
    return {"discoveries": {str(d["id"]): {"title": d["title"], "state": d["state"]} for d in r["discoveries"]},
            "apps": [a["app_id"] for a in r["apps"]], "gaps": [g["id"] for g in r["gaps"]]}


def check_one(store: Store, wid: int, *, now: Optional[float] = None) -> dict[str, Any]:
    now = now or time.time()
    w = get(store, wid)
    snap = _snapshot(store, w["question"])
    before = w.get("seen")
    news: dict[str, Any] = {}
    if before is not None:
        old_disc = before.get("discoveries") or {}
        new_disc = [{"id": int(k), **v} for k, v in snap["discoveries"].items() if k not in old_disc]
        changed = [{"id": int(k), "title": v["title"], "from": old_disc[k].get("state"), "to": v["state"]}
                   for k, v in snap["discoveries"].items() if k in old_disc and old_disc[k].get("state") != v["state"]]
        new_apps = [a for a in snap["apps"] if a not in (before.get("apps") or [])]
        if new_disc:
            news["discoveries"] = new_disc
        if changed:
            news["state_changes"] = changed
        if new_apps:
            news["apps"] = new_apps
    with store.tx() as c:
        c.execute("UPDATE watches SET seen=?, last_checked=?, updated=?" + (", last_news=?, last_news_at=?" if news else "") + " WHERE id=?",
                  (_j(snap), now, now, *((_j(news), now) if news else ()), wid))
    return {"id": wid, "question": w["question"], "baseline": before is None, "news": news, "notify": bool(news)}


def check_all(store: Store, *, now: Optional[float] = None) -> dict[str, Any]:
    results = [check_one(store, r["id"], now=now) for r in store.q("SELECT id FROM watches WHERE state='activa' ORDER BY id")]
    with_news = [r for r in results if r["notify"]]
    store.set_meta("watches_checked_at", now or time.time())
    return {"checked": len(results), "with_news": with_news, "notify": bool(with_news),
            "summary": (f"{len(with_news)} preguntas guardadas con novedades." if with_news else "Sin novedades en las preguntas guardadas.")}


def set_state(store: Store, wid: int, *, state: str = "", delete: bool = False, clear_news: bool = False) -> dict[str, Any]:
    get(store, wid)
    with store.tx() as c:
        if delete:
            c.execute("DELETE FROM watches WHERE id=?", (wid,))
            return {"deleted": wid}
        if state:
            if state not in STATES:
                raise ValueError(f"State must be one of {', '.join(STATES)}.")
            c.execute("UPDATE watches SET state=?, updated=? WHERE id=?", (state, time.time(), wid))
        if clear_news:
            c.execute("UPDATE watches SET last_news=NULL, updated=? WHERE id=?", (time.time(), wid))
    return get(store, wid)
