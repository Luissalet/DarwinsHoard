"""darwin_discuss: one Ágora thread per proposal, kept on it; notes are posted as darwin, marked as Luis's."""
from darwin_hoard import debate
from darwin_hoard.store import Store


def test_one_thread_per_proposal_and_notes_are_attributed(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="a/b", title="b")
    pid = store.upsert_proposal(key="k", source_id=sid, target="talos", state="pendiente", origin="agent", reason="Actas")
    calls = []

    def fetch(url, body=None, *, method="GET", timeout=5.0, headers=None):
        calls.append((method, url.split("/api/agora/")[1], body))
        if url.endswith("/thread_open"):
            return 200, {"ok": True, "thread": {"id": 77}}, ""
        if url.endswith("/post"):
            return 200, {"ok": True}, ""
        return 200, {"thread": {"title": "t", "status": "open"}, "messages": [{"agent": "darwin", "kind": "proposal", "body": "x", "created": 1}]}, ""

    out = debate.discuss(store, pid, "http://hub", {}, fetch)
    assert out["thread"]["id"] == 77 and out["messages"][0]["by"] == "darwin"
    opened = [c for c in calls if c[1] == "thread_open"][0][2]
    assert opened["agent"] == "darwin" and opened["space_id"] == "darwin" and "talos" in opened["body"]
    debate.discuss(store, pid, "http://hub", {}, fetch, note="Me interesa")
    posts = [c for c in calls if c[1] == "post"]
    assert len([c for c in calls if c[1] == "thread_open"]) == 1
    assert posts and posts[0][2]["thread_id"] == 77 and "Nota de Luis" in posts[0][2]["body"]


def test_refused_thread_raises(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="a/b", title="b")
    pid = store.upsert_proposal(key="k", source_id=sid, target="talos")
    try:
        debate.discuss(store, pid, "http://hub", {}, lambda *a, **k: (401, {"ok": False, "error": "no token"}, ""))
    except RuntimeError as exc:
        assert "no token" in str(exc)
    else:
        raise AssertionError("expected an error")
    assert store.one("SELECT agora_thread FROM proposals WHERE id=?", (pid,))["agora_thread"] is None
