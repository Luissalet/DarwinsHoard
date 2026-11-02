"""Debate a proposal in the Ágora (``darwin_discuss``).

A proposal opens one thread in the hub's Ágora (space ``darwin`` by default) with the discovery, its genealogy and the
proposed app; the thread id is kept on the proposal (``agora_thread``) so the next call shows the same thread instead
of opening another. Darwin writes as the agent ``darwin``: only the hub's own page may write as Luis, so a note Luis
types here is posted by ``darwin`` and says it is his."""

from __future__ import annotations

from typing import Any, Callable, Optional

from . import query
from .store import Store

Fetch = Callable[..., tuple[Optional[int], Any, str]]
SPACE = "darwin"


def _body(store: Store, prop: dict[str, Any], note: str) -> str:
    g = query.genealogy(store, source_id=prop["source_id"]) or {}
    src = g.get("source") or {}
    lines = [f"Descubrimiento #{prop['source_id']}: {src.get('title') or src.get('repo') or src.get('url')}",
             f"Enlace: {src.get('url') or ''}",
             f"Propuesta: {prop.get('target') or 'sin app'} · estado {prop.get('state')} · origen {prop.get('origin') or '?'}",
             f"Motivo: {prop.get('reason') or '—'}",
             f"Estado agregado: {g.get('state')}; otras propuestas: " +
             (", ".join(f"{p.get('target')}={p.get('state')}" for p in g.get("proposals") or [] if p.get("id") != prop["id"]) or "ninguna")]
    if note:
        lines.append(f"Nota de Luis (escrita en Darwin's Hoard): {note}")
    lines.append("¿Encaja? ¿En qué app y con qué alcance? Decidid y dejad el estado en Darwin (darwin_set_state).")
    return "\n".join(lines)


def discuss(store: Store, proposal_id: int, hub: str, headers: dict[str, str], fetch: Fetch, *, note: str = "",
            space: str = SPACE) -> dict[str, Any]:
    prop = store.one("SELECT * FROM proposals WHERE id=?", (proposal_id,))
    if not prop:
        raise LookupError(f"Proposal {proposal_id} does not exist.")
    thread_id = prop.get("agora_thread")
    if not thread_id:
        title = f"Darwin: ¿{(store.source(prop['source_id']) or {}).get('title') or 'descubrimiento'} para {prop.get('target') or 'qué app'}?"
        status, resp, why = fetch(hub + "/api/agora/thread_open", {"agent": "darwin", "space_id": space, "kind": "debate",
                                                                   "title": title[:200], "body": _body(store, prop, note)},
                                  method="POST", timeout=15.0, headers=headers)
        if status != 200 or not isinstance(resp, dict) or not resp.get("ok"):
            raise RuntimeError(f"The Ágora did not open the thread: {(resp or {}).get('error') if isinstance(resp, dict) else why or status}")
        thread_id = int(resp["thread"]["id"])
        with store.tx() as c:
            c.execute("UPDATE proposals SET agora_thread=?, agora_space=COALESCE(agora_space, ?) WHERE id=?", (thread_id, space, proposal_id))
    elif note:
        status, resp, why = fetch(hub + "/api/agora/post", {"agent": "darwin", "space_id": prop.get("agora_space") or space,
                                                            "thread_id": thread_id, "kind": "comment",
                                                            "body": f"Nota de Luis (escrita en Darwin's Hoard): {note}"},
                                  method="POST", timeout=15.0, headers=headers)
        if status != 200 or not isinstance(resp, dict) or not resp.get("ok"):
            raise RuntimeError(f"The Ágora did not take the note: {(resp or {}).get('error') if isinstance(resp, dict) else why or status}")
    return thread(store, proposal_id, hub, headers, fetch)


def thread(store: Store, proposal_id: int, hub: str, headers: dict[str, str], fetch: Fetch) -> dict[str, Any]:
    prop = store.one("SELECT id, agora_thread, agora_space FROM proposals WHERE id=?", (proposal_id,))
    if not prop or not prop.get("agora_thread"):
        return {"thread": None, "messages": []}
    space = prop.get("agora_space") or SPACE
    status, resp, why = fetch(f"{hub}/api/agora/threads/{prop['agora_thread']}?space_id={space}", method="GET", timeout=10.0,
                              headers=headers)
    if status != 200 or not isinstance(resp, dict):
        return {"thread": {"id": prop["agora_thread"], "space": space}, "messages": [], "error": why or f"HTTP {status}"}
    th = resp.get("thread") or resp
    msgs = resp.get("messages") or th.get("messages") or []
    return {"thread": {"id": prop["agora_thread"], "space": space, "title": th.get("title"), "status": th.get("status")},
            "messages": [{"by": m.get("agent") or m.get("author"), "kind": m.get("kind"), "body": m.get("body"),
                          "at": m.get("created") or m.get("at")} for m in msgs][-30:]}
