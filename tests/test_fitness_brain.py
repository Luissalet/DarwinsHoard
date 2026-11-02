"""Fitness scores open discoveries with reasons; the Brain export writes linked notes and never touches a person's note."""
import time

from darwin_hoard import brain_export, fitness, query
from darwin_hoard.store import Store


def _seed(tmp_path):
    store = Store(tmp_path / "d.db")
    with store.tx() as c:
        c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail) VALUES ('app:talos','hoardhub','app',"
                  "'Talos''s Hoard','talos','observation')")
    store.add_gap(title="Transcribir reuniones largas", detail="audio meeting transcription", target="talos")
    hot = store.upsert_source(repo="a/meeting-transcriber", title="meeting transcription tool", stars="12k", license="MIT",
                              seen_at=time.time())
    store.upsert_proposal(key="p1", source_id=hot, target="talos", state="pendiente", origin="agent")
    done = store.upsert_source(repo="b/done", title="done", stars="50k", seen_at=time.time())
    store.upsert_proposal(key="p2", source_id=done, target="talos", state="descartada", origin="luis")
    return store, hot, done


def test_fitness_scores_open_discoveries_with_reasons(tmp_path):
    store, hot, done = _seed(tmp_path)
    items = {i["id"]: i for i in query.find(store, order="fitness", limit=10)["items"]}
    assert items[hot]["fitness"] >= 60 and items[done]["fitness"] == 0
    assert any("carencia" in r for r in items[hot]["fitness_reasons"])
    assert query.genealogy(store, source_id=hot)["fitness"]["score"] == items[hot]["fitness"]
    assert fitness.stars_of("1.2k") == 1200 and fitness.stars_of("") == 0


def test_brain_export_writes_linked_notes_and_respects_personal_ones(tmp_path):
    store, hot, done = _seed(tmp_path)
    vault = tmp_path / "vault" / "admin"
    mine = vault / "Notes" / "Darwin" / "Darwin.md"
    out = brain_export.export(store, vault)
    index = (vault / "Notes" / "Darwin" / "Darwin.md").read_text(encoding="utf-8")
    assert "generated_by: darwins-hoard" in index and "[[Darwin · Talos's Hoard]]" in index
    app = (vault / "Notes" / "Darwin" / "Apps" / "Darwin · Talos's Hoard.md").read_text(encoding="utf-8")
    assert f"[[Darwin {hot} · a meeting-transcriber]]" in app and "Transcribir reuniones largas" in app
    assert out["discoveries"] == 1  # the discarded one is not a live note
    stale = vault / "Notes" / "Darwin" / "Descubrimientos" / "old.md"
    stale.write_text("---\ngenerated_by: darwins-hoard\n---\nold", encoding="utf-8")
    personal = vault / "Notes" / "Darwin" / "mine.md"
    personal.write_text("my own note", encoding="utf-8")
    again = brain_export.export(store, vault)
    assert again["removed"] == 1 and not stale.exists() and personal.read_text(encoding="utf-8") == "my own note"
    mine.write_text("hand written, no marker", encoding="utf-8")
    brain_export.export(store, vault)
    assert mine.read_text(encoding="utf-8") == "hand written, no marker"


def test_hashes_in_texts_do_not_become_brain_tags():
    assert brain_export.plain("radar #123 and #agents, C# stays") == "radar 123 and agents, C# stays"
