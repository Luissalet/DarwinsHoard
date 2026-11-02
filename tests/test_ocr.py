"""Screenshots in the inbox: OCR text → links and confirmed repositories, read once, safe file access."""
import time
from pathlib import Path

from darwin_hoard import ocr
from darwin_hoard.store import Store


def _capture(store: Store, key: str, attachment: str) -> int:
    cid, _ = store.add_capture(capture_key=key, channel="whatsapp", text="", attachment=attachment, at=time.time())
    return cid


def test_screenshots_are_read_once_and_only_confirmed_repos_link(tmp_path: Path):
    store = Store(tmp_path / "d.db")
    media = tmp_path / "media"
    media.mkdir()
    (media / "AAA111.jpg").write_bytes(b"jpg")
    (media / "BBB222.png").write_bytes(b"png")
    a = _capture(store, "w:1", '"AAA111.jpg"')
    b = _capture(store, "w:2", '"BBB222.png"')
    c = _capture(store, "w:3", '"CCC333.jpg"')      # file gone
    _capture(store, "w:4", '"DDD444.mp4"')          # not an image: left alone
    texts = {"AAA111.jpg": "Check microsoft/markitdown and/or this: https://x.com/u/status/5?a=zz",
             "BBB222.png": "nothing useful here"}
    calls = []

    def fake_ocr(path):
        calls.append(Path(path).name)
        return {"ok": True, "text": texts[Path(path).name], "backend": "fake"}

    exists = {"microsoft/markitdown": True, "and/or": False}
    result = ocr.read_inbox(store, media, fake_ocr, repo_check=lambda r: exists.get(r, False))
    assert result["read"] == 2 and result["linked"] == 1 and result["missing"] == 1
    assert set(result["found"]) == {"https://github.com/microsoft/markitdown", "https://x.com/u/status/5"}
    keys = {r["key"] for r in store.q("SELECT key FROM sources")}
    assert keys == {"repo:microsoft/markitdown", "url:https://x.com/u/status/5"}
    assert store.one("SELECT COUNT(*) AS n FROM capture_sources WHERE capture_id=?", (a,))["n"] == 2
    assert store.one("SELECT declared FROM captures WHERE id=?", (b,))["declared"]["ocr"]["refs"] == []
    assert "error" in store.one("SELECT declared FROM captures WHERE id=?", (c,))["declared"]["ocr"]
    again = ocr.read_inbox(store, media, fake_ocr, repo_check=lambda r: True)
    assert again["read"] == 0 and sorted(calls) == ["AAA111.jpg", "BBB222.png"]


def test_unavailable_ocr_stops_without_marking(tmp_path: Path):
    store = Store(tmp_path / "d.db")
    media = tmp_path / "media"
    media.mkdir()
    (media / "AAA111.jpg").write_bytes(b"jpg")
    cid = _capture(store, "w:1", '"AAA111.jpg"')
    result = ocr.read_inbox(store, media, lambda p: {"ok": False, "error": "Kafka is off", "kind": "unavailable"})
    assert result["error"] == "Kafka is off" and result["remaining"] == 1
    assert "ocr" not in (store.one("SELECT declared FROM captures WHERE id=?", (cid,))["declared"] or {})


def test_media_path_never_leaves_the_folder(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    (tmp_path / "secret.jpg").write_bytes(b"x")
    assert ocr.media_path(media, '"../secret.jpg"') is None
    assert ocr.media_path(media, '"..\\\\secret.jpg"') is None
    assert ocr.attachment_name('{"file": "ABC123.jpg"}') == "ABC123.jpg"
