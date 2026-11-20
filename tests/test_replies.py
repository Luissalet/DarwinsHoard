"""Quoted replies in the chat: the comment is kept with what it answers, linked to the same discovery, shown with it."""
import json

from darwin_hoard import query, replies, triage
from darwin_hoard.store import Store
from darwin_ingest import sync_whatsapp_page

CHAT = "120363000000000000@g.us"
REEL = "https://www.instagram.com/reel/AbC123xyz/?psln=zzz"
COVERAGE = {"scope": "retained_bridge_store", "phone_history_complete": False}


def _msg(mid, text, ts, *, reply_to=None, from_me=True):
    m = {"id": mid, "chat": CHAT, "text": text, "ts": ts, "from": "34600000000@s.whatsapp.net", "from_me": from_me, "kind": "text"}
    if reply_to:
        m["reply_to"] = reply_to
    return m


def _client(*messages):
    def client(*, chat, cursor, limit):
        return {"messages": list(messages), "has_more": False, "next_cursor": None, "coverage": COVERAGE}
    return client


def _sync(store, *messages):
    return sync_whatsapp_page(store, _client(*messages), account="test-account", chat=CHAT)


QUOTE = {"id": "LINK1", "from_name": "me", "from_me": True, "text": REEL}


def test_a_reply_is_kept_and_linked_to_the_discovery_of_the_message_it_quotes(tmp_path):
    store = Store(tmp_path / "d.db")
    out = _sync(store, _msg("LINK1", REEL, 100), _msg("C1", "Esto me parece muy interesante para Blood Arrows", 110, reply_to=QUOTE))
    assert out["replies"] == 1
    sid = store.q("SELECT id FROM sources WHERE key LIKE 'url:%AbC123xyz%'")[0]["id"]
    comment = store.one("SELECT * FROM captures WHERE json_extract(provenance,'$.message_id')='C1'")
    assert comment["provenance"]["reply_to_id"] == "LINK1" and comment["declared"]["reply_to"]["text"] == REEL
    assert comment["declared"]["reply_to"]["capture_id"]
    assert {r["source_id"] for r in store.q("SELECT source_id FROM capture_sources WHERE capture_id=?", (comment["id"],))} == {sid}
    got = replies.comments_of(store, sid, only_mine=True)
    assert [c["line"] for c in got] == [f"Cuenta propia: Esto me parece muy interesante para Blood Arrows (en respuesta a {REEL})"]
    g = query.genealogy(store, source_id=sid)
    assert g["own_comments"] == 1 and g["comments"][0]["quoted_id"] == "LINK1"
    assert any(c["reply"] for c in g["captures"])
    assert query.inbox(store)["total"] == 0                       # the comment is no longer an orphan


def test_the_quoted_message_may_arrive_after_the_comment(tmp_path):
    store = Store(tmp_path / "d.db")
    quote = {"id": "IMG1", "from_name": "me", "from_me": True, "text": ""}      # a screenshot: no text to read a link from
    _sync(store, _msg("C2", "Gráficos durante el trabajo en el Ágora", 120, reply_to=quote))
    assert query.inbox(store)["items"][0]["reply"]["quoted_id"] == "IMG1"   # still says what it answers
    shot = store.upsert_source(url="https://github.com/acme/widgets")
    cap = _sync(store, _msg("IMG1", "", 100))["captures"][0]
    store.link_capture(cap, shot)                                  # the screenshot was read later
    assert replies.relink(store)["linked"] == 1
    assert [c["text"] for c in replies.comments_of(store, shot)] == ["Gráficos durante el trabajo en el Ágora"]
    assert replies.relink(store)["linked"] == 0                    # idempotent


def test_a_pass_from_the_start_completes_stored_captures_without_duplicating_them(tmp_path):
    store = Store(tmp_path / "d.db")
    messages = (_msg("LINK1", REEL, 100), _msg("C1", "Interesante", 110, reply_to=QUOTE))
    _sync(store, *messages)
    before = store.one("SELECT COUNT(*) AS n FROM captures")["n"]
    # captures stored by an older version, before replies were kept
    with store.tx() as c:
        c.execute("UPDATE captures SET declared=json_remove(declared,'$.reply_to'), provenance=json_remove(provenance,'$.reply_to_id')")
        c.execute("DELETE FROM capture_sources WHERE capture_id=(SELECT id FROM captures WHERE json_extract(provenance,'$.message_id')='C1')")
    out = _sync(store, *messages)
    assert out["created"] == 0 and out["replies"] == 1 and out["reply_links"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM captures")["n"] == before


def test_comments_query_filters_and_other_people_are_told_apart(tmp_path):
    store = Store(tmp_path / "d.db")
    _sync(store, _msg("LINK1", REEL, 100), _msg("C1", "Para Blood Arrows", 110, reply_to=QUOTE),
          _msg("C3", "Yo lo vi ayer", 120, reply_to=QUOTE, from_me=False))
    assert replies.comments(store)["total"] == 1
    both = replies.comments(store, from_me=False)
    assert both["total"] == 2 and {i["who"] for i in both["items"]} == {"Cuenta propia", "Otra persona del grupo"}
    assert replies.comments(store, query="blood")["items"][0]["sources"][0]["key"].startswith("url:")
    assert [i["own_comments"] for i in query.find(store, commented=True)["items"]] == [1]
    assert query.find(store, commented=False)["total"] == 0


def test_comment_leads_the_triage_material_and_the_score(tmp_path):
    store = Store(tmp_path / "d.db")
    _sync(store, _msg("LINK1", REEL, 100), _msg("C1", "Para Blood Arrows", 110, reply_to=QUOTE))
    src = store.one("SELECT * FROM sources WHERE key LIKE 'url:%AbC123xyz%'")
    assert triage._material(store, src).startswith("COMENTARIO PROPIO (contexto principal):\nCuenta propia: Para Blood Arrows")
    assert triage.pending(store)[0]["id"] == src["id"]
    item = query.find(store, with_fitness=True)["items"][0]
    assert "Comentario propio en el chat (+20)" in item["fitness_reasons"]
    assert json.dumps(replies.normalize({"id": "x", "text": "t" * 5000})["text"]).count("t") == replies.QUOTE_CHARS
