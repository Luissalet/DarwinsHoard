"""darwin_ask: local retrieval feeds the model; citations are checked; no model still returns the material."""
from darwin_hoard import ask
from darwin_hoard.store import Store


def _seed(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="leonxlnx/earshot", title="earshot: meeting transcription")
    store.upsert_proposal(key="p1", source_id=sid, target="talos", state="aceptada", origin="luis")
    other = store.upsert_source(repo="foo/unrelated", title="a game engine")
    return store, sid, other


def test_retrieval_ranks_by_shared_words_and_works_without_model(tmp_path):
    store, sid, other = _seed(tmp_path)
    out = ask.ask(store, "¿Qué tenemos para transcribir reuniones?")
    ids = [d["id"] for d in out["discoveries"]]
    assert sid in ids and other not in ids
    assert out["answer"] is None and "No model" in out["note"]


def test_answer_keeps_only_citations_that_exist(tmp_path):
    store, sid, _ = _seed(tmp_path)
    seen = {}

    def fake_chat(messages, **kw):
        seen["material"] = messages[-1]["content"]
        return {"ok": True, "json": {"answer": f"Earshot [#{sid}] va a Talos.", "discoveries": [sid, 9999]}, "model": "fake"}

    out = ask.ask(store, "transcribir reuniones", chat=fake_chat)
    assert f"[#{sid}]" in seen["material"] and "talos=aceptada" in seen["material"]
    assert out["answer"].startswith("Earshot") and out["cited"] == [sid] and out["model"] == "fake"


def test_model_failure_is_reported_not_raised(tmp_path):
    store, _, _ = _seed(tmp_path)
    out = ask.ask(store, "transcribir", chat=lambda *a, **k: {"ok": False, "error": "no_model", "detail": "nothing loaded"})
    assert out["answer"] is None and "no_model" in out["note"] and out["discoveries"]
