"""«Who does X?» never answers with an app whose description denies doing X."""

from __future__ import annotations

from darwin_hoard import tree
from darwin_hoard.store import Store

NEGATIVE = ("Publish the derived atlas of the family as a static page. Does not perform OCR, transcription or model inference. "
            "Writes HTML.")


def _store(tmp_path):
    store = Store(tmp_path / "d.db")
    rows = [
        ("faustus", None, "root", "Faustus", "faustus", ""),
        ("hoardhub", "faustus", "hub", "Hoard Hub", "hoardhub", "The family hub"),
        ("tool:hub_atlas_derived_publish", "hoardhub", "tool", "hub_atlas_derived_publish", "hoardhub", NEGATIVE),
        ("app:kafka", "hoardhub", "app", "Kafka's Hoard", "kafka", "Paperwork and deadlines"),
        ("tool:kafka_ocr", "app:kafka", "tool", "kafka_document_read", "kafka", "Read a scanned letter with OCR and extract its deadlines."),
        ("app:funes", "hoardhub", "app", "Funes's Hoard", "funes", "Meetings"),
        ("tool:funes_transcribe", "app:funes", "tool", "funes_transcribe", "funes", "Transcription of meeting audio with speech models."),
    ]
    with store.tx() as c:
        for key, parent, level, name, app, detail in rows:
            c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail) VALUES (?,?,?,?,?,?)",
                      (key, parent, level, name, app, detail))
    return store


def test_negated_description_is_not_a_provider(tmp_path):
    store = _store(tmp_path)
    apps = [a["app_id"] for a in tree.find(store, "¿dónde hacemos OCR?")["apps"]]
    assert apps == ["kafka"]
    apps = [a["app_id"] for a in tree.find(store, "transcribir audio de reuniones")["apps"]]
    assert "funes" in apps and "hoardhub" not in apps
    # the affirmed part of the same description still matches
    assert [a["app_id"] for a in tree.find(store, "derived atlas")["apps"]] == ["hoardhub"]
    store.close()


def test_affirmed_keeps_what_is_not_denied():
    assert "ocr" not in tree.affirmed("does not perform ocr, transcription or model inference. writes html.")
    assert "html" in tree.affirmed("does not perform ocr, transcription or model inference. writes html.")
    assert "ocr" not in tree.affirmed("it doesn't do ocr")
    assert "ocr" not in tree.affirmed("no hace ocr ni transcripcion")
    assert "ocr" in tree.affirmed("not only ocr but also layout")
    assert "ocr" in tree.affirmed("si no hay texto, usa ocr")
    assert "code" in tree.affirmed("a no-code builder")
    assert "ocr" in tree.affirmed("works without internet; reads screenshots with ocr")
    assert "ocr" in tree.affirmed("never uploads files, but runs ocr locally")
