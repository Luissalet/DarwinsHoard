"""darwin_triage: picks only real app ids, never overrides Luis, triages each discovery once."""
from darwin_hoard import triage
from darwin_hoard.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "d.db")
    with store.tx() as c:
        for key, app, name in (("app:talos", "talos", "Talos's Hoard"), ("app:writer", "writer", "Writer's Hoard")):
            c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail, evidence, operation) VALUES (?,?,?,?,?,?,?,?)",
                      (key, "hoardhub", "app", name, app, "observation and audio" if app == "talos" else "writing", "declarada", "disponible"))
    return store


def test_triage_proposes_known_apps_and_marks_the_rest(tmp_path):
    store = _store(tmp_path)
    a = store.upsert_source(repo="x/meeting-notes", title="meeting transcription")
    b = store.upsert_source(url="https://x.com/someone", title="profile")
    c = store.upsert_source(repo="x/thing", title="thing")
    owned = store.upsert_source(repo="x/owned", title="owned")
    store.upsert_proposal(key="k", source_id=owned, target="writer", state="descartada", origin="luis")
    answers = {"meeting transcription": {"app": "talos", "reason": "Actas.", "useful": True},
               "profile": {"app": None, "reason": "Perfil sin contenido.", "useful": False},
               "thing": {"app": "made-up", "reason": "?", "useful": True}}

    def fake_chat(messages, **kw):
        title = messages[-1]["content"].split("Título: ")[1].split("\n")[0]
        return {"ok": True, "json": answers[title], "model": "fake"}

    out = triage.run(store, fake_chat)
    assert [p["source_id"] for p in out["proposed"]] == [a] and out["noise"] == 1 and out["skipped"] == 1
    assert store.one("SELECT target, origin, state FROM proposals WHERE source_id=?", (a,)) == {"target": "talos", "origin": "agent", "state": "pendiente"}
    assert store.one("SELECT COUNT(*) AS n FROM proposals WHERE source_id=?", (owned,))["n"] == 1
    assert triage.run(store, fake_chat)["proposed"] == []


def test_model_down_stops_and_keeps_the_rest_pending(tmp_path):
    store = _store(tmp_path)
    store.upsert_source(repo="x/a", title="a")
    out = triage.run(store, lambda *a, **k: {"ok": False, "error": "no_model", "detail": ""})
    assert out["remaining"] == 1 and "no_model" in out["error"]
    assert len(triage.pending(store)) == 1
