"""Quoted replies in the chat: a comment answers a message, and the message is what the comment is about.

Luis answers a reel with a sentence («esto me parece muy interesante para Blood Arrows»). The bridge gives every message
its ``reply_to`` (the quoted message's id, author and text); Darwin keeps it on the comment's capture
(``declared.reply_to``, and ``provenance.reply_to_id``) and links the comment to the same discoveries as the quoted
message, so the comment shows next to the discovery as «Luis: … (en respuesta a …)». If the quoted message has not
arrived yet, the link is made when it does: :func:`relink` is idempotent and runs after every sync and every read of
screenshots or posts (a quoted screenshot gets its discovery only once it has been read)."""

from __future__ import annotations

import json
from typing import Any, Optional

from .canon import extract_refs
from .store import Store

QUOTE_CHARS = 600
LINE_CHARS = 160
HAS_REPLY = "json_extract(c.declared,'$.reply_to.id') IS NOT NULL"
FROM_ME = "json_extract(c.provenance,'$.from_me')=1"


def normalize(reply: Any) -> Optional[dict[str, Any]]:
    """The part of a bridge ``reply_to`` worth keeping, or ``None`` if the message quotes nothing identifiable."""
    if not isinstance(reply, dict) or not isinstance(reply.get("id"), str) or not reply["id"]:
        return None
    return {"id": reply["id"], "from_name": str(reply.get("from_name") or "")[:80], "from_me": bool(reply.get("from_me")),
            "text": str(reply.get("text") or "")[:QUOTE_CHARS]}


def record(store: Store, capture_id: int, reply: Any) -> bool:
    """Keep the quote on the capture (idempotent). Returns whether something changed."""
    quote = normalize(reply)
    if not quote:
        return False
    with store.tx() as c:
        row = c.execute("SELECT declared, provenance FROM captures WHERE id=?", (capture_id,)).fetchone()
        if row is None:
            return False
        declared, prov = json.loads(row["declared"] or "{}"), json.loads(row["provenance"] or "{}")
        old = declared.get("reply_to") or {}
        merged = {**old, **quote}          # capture_id of the quoted capture, found by relink, survives
        if declared.get("reply_to") == merged and prov.get("reply_to_id") == quote["id"]:
            return False
        declared["reply_to"], prov["reply_to_id"] = merged, quote["id"]
        c.execute("UPDATE captures SET declared=?, provenance=? WHERE id=?",
                  (json.dumps(declared, ensure_ascii=False, sort_keys=True), json.dumps(prov, ensure_ascii=False, sort_keys=True), capture_id))
    return True


def _sources_of_quote(store: Store, chat: str, quote: dict[str, Any]) -> tuple[Optional[int], list[int]]:
    """The quoted capture (if Darwin holds it) and every discovery it points at: those its capture is linked to, plus the
    links written in the quoted text itself (a reel quoted before its own capture reached Darwin still resolves)."""
    quoted = store.one("SELECT id FROM captures WHERE channel='whatsapp' AND chat=? AND json_extract(provenance,'$.message_id')=? "
                       "ORDER BY id LIMIT 1", (chat, quote["id"]))
    ids: set[int] = set()
    if quoted:
        ids.update(r["source_id"] for r in store.q("SELECT source_id FROM capture_sources WHERE capture_id=?", (quoted["id"],)))
        ids.update(r["source_id"] for r in store.q("SELECT source_id FROM captures WHERE id=? AND source_id IS NOT NULL", (quoted["id"],)))
    for ref in extract_refs(quote.get("text") or ""):
        found = store.source_by_key(ref["key"])
        if found:
            ids.add(found["id"])
        elif ref["kind"] != "candidate":
            ids.add(store.upsert_source(url=ref["url"], meta={"identity_evidence": "url", "github_verified": False}))
    return (quoted["id"] if quoted else None), sorted(ids)


def relink(store: Store, capture_ids: Optional[list[int]] = None) -> dict[str, int]:
    """Link every quoting capture to the discoveries of the message it quotes. ``capture_ids`` limits the pass; without it,
    all of them are looked at (a few thousand rows at most, so cheap enough to run after each sync)."""
    sql = f"SELECT c.id, c.chat, json_extract(c.declared,'$.reply_to') AS reply FROM captures c WHERE {HAS_REPLY}"
    args: list[Any] = []
    if capture_ids is not None:
        if not capture_ids:
            return {"replies": 0, "linked": 0, "unresolved": 0}
        sql += f" AND c.id IN ({','.join('?' * len(capture_ids))})"
        args = list(capture_ids)
    out = {"replies": 0, "linked": 0, "unresolved": 0}
    for row in store.q(sql, args):
        quote = row["reply"] if isinstance(row["reply"], dict) else json.loads(row["reply"] or "{}")
        if not quote.get("id"):
            continue
        out["replies"] += 1
        quoted_id, sources = _sources_of_quote(store, row["chat"], quote)
        if quoted_id and quote.get("capture_id") != quoted_id:
            store.set_capture_declared(row["id"], "reply_to", {**quote, "capture_id": quoted_id})
        if not sources:
            out["unresolved"] += 1
            continue
        have = {r["source_id"] for r in store.q("SELECT source_id FROM capture_sources WHERE capture_id=?", (row["id"],))}
        for sid in sources:
            if sid not in have:
                store.link_capture(row["id"], sid)
                out["linked"] += 1
    return out


def _shorten(text: str, n: int = LINE_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def describe(capture: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A capture that answers a message, in the shape the page and the tools show it; ``None`` if it answers nothing."""
    declared = capture.get("declared") if isinstance(capture.get("declared"), dict) else json.loads(capture.get("declared") or "{}")
    provenance = capture.get("provenance") if isinstance(capture.get("provenance"), dict) else json.loads(capture.get("provenance") or "{}")
    reply = declared.get("reply_to")
    if not isinstance(reply, dict) or not reply.get("id"):
        return None
    luis = bool(provenance.get("from_me"))
    who = "Luis" if luis else "Otra persona del grupo"
    quoted = _shorten(reply.get("text") or "") or (f"un mensaje de {reply['from_name']}" if reply.get("from_name") else "un mensaje")
    text = (capture.get("text") or "").strip()
    return {"capture_id": capture["id"], "at": capture.get("at"), "from_luis": luis, "who": who, "text": text,
            "quoted_id": reply["id"], "quoted_text": reply.get("text") or "", "quoted_from": reply.get("from_name") or "",
            "quoted_capture_id": reply.get("capture_id"),
            "line": f"{who}: {_shorten(text, 300)} (en respuesta a {quoted})" if text else f"{who}: (sin texto) (en respuesta a {quoted})"}


def comments_of(store: Store, source_id: int, *, only_luis: bool = False) -> list[dict[str, Any]]:
    rows = store.q("SELECT c.* FROM captures c WHERE c.id IN (SELECT capture_id FROM capture_sources WHERE source_id=?) "
                   f"AND {HAS_REPLY}{' AND ' + FROM_ME if only_luis else ''} ORDER BY c.at", (source_id,))
    return [d for d in (describe(r) for r in rows) if d]


def counts_by_source(store: Store, ids: list[int]) -> dict[int, dict[str, Any]]:
    """For a page of discoveries: how many comments of Luis each has and the latest one as a line."""
    out: dict[int, dict[str, Any]] = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        if not part:
            continue
        rows = store.q("SELECT cs.source_id AS sid, c.* FROM capture_sources cs JOIN captures c ON c.id=cs.capture_id "
                       f"WHERE cs.source_id IN ({','.join('?' * len(part))}) AND {HAS_REPLY} AND {FROM_ME} ORDER BY c.at", part)
        for r in rows:
            d = describe(r)
            if d:
                slot = out.setdefault(r["sid"], {"count": 0, "line": ""})
                slot["count"] += 1
                slot["line"] = d["line"]
    return out


def context_for(store: Store, source_id: int, limit: int = 3) -> str:
    """The comments of Luis on a discovery as plain lines: the main context for triage and proposals."""
    return "\n".join(c["line"] for c in comments_of(store, source_id, only_luis=True)[-limit:])


def comments(store: Store, *, from_luis: bool = True, query: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Every comment that answers a message, newest first, with the discoveries it ended up linked to."""
    where, args = [HAS_REPLY], []
    if from_luis:
        where.append(FROM_ME)
    if query.strip():
        where.append("(LOWER(c.text) LIKE ? OR LOWER(json_extract(c.declared,'$.reply_to.text')) LIKE ?)")
        args += [f"%{query.strip().lower()}%"] * 2
    total = store.one(f"SELECT COUNT(*) AS n FROM captures c WHERE {' AND '.join(where)}", args)["n"]
    rows = store.q(f"SELECT c.* FROM captures c WHERE {' AND '.join(where)} ORDER BY c.at DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    items = []
    for r in rows:
        d = describe(r)
        if not d:
            continue
        d["sources"] = store.q("SELECT s.id, s.key, s.title, s.url FROM sources s JOIN capture_sources cs ON cs.source_id=s.id WHERE cs.capture_id=? "
                               "ORDER BY s.id", (r["id"],))
        items.append(d)
    return {"total": total, "offset": offset, "limit": limit, "items": items}
