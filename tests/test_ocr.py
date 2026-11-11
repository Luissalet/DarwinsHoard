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


def test_layout_blocks_are_read_one_by_one_and_wrapped_links_join(tmp_path: Path):
    store = Store(tmp_path / "d.db")
    media = tmp_path / "media"
    media.mkdir()
    (media / "AAA111.jpg").write_bytes(b"jpg")
    cid = _capture(store, "w:1", '"AAA111.jpg"')
    layout = [{"label": "Page-Header", "bbox": [0, 0, 10, 10], "text": "18:09"},
              {"label": "Text", "bbox": [0, 20, 10, 30], "text": "1 Personal Vault Template github.com/kepano/\nkepano-obsidian"},
              {"label": "Text", "bbox": [0, 40, 10, 50], "text": "2 JSON Canvas github.com/obsidianmd/jsoncanvas\nnext line"},
              {"label": "Picture", "bbox": [0, 60, 10, 70], "text": ""}]
    text = "\n".join(b["text"] for b in layout)

    def fake_ocr(path):
        return {"ok": True, "text": text, "layout": layout, "backend": "indra",
                "engine_report": {"requested": "auto", "used": "indra", "fallback": False, "reason": ""}}

    result = ocr.read_inbox(store, media, fake_ocr, repo_check=lambda r: True, repo_list=lambda o: None)
    assert set(result["found"]) == {"https://github.com/kepano/kepano-obsidian", "https://github.com/obsidianmd/jsoncanvas"}
    declared = store.one("SELECT declared FROM captures WHERE id=?", (cid,))["declared"]["ocr"]
    assert declared["layout_blocks"] == 3 and [b["refs"] for b in declared["blocks"]] == [["https://github.com/kepano/kepano-obsidian"],
                                                                                      ["https://github.com/obsidianmd/jsoncanvas"]]
    assert "engine_fallback" not in declared


def test_rejoin_only_joins_links_cut_at_a_slash_or_dash():
    assert ocr.rejoin("see github.com/kepano/\nkepano-obsidian today") == "see github.com/kepano/kepano-obsidian\ntoday"
    assert ocr.rejoin("github.com/addyosmani/agent-\nskills") == "github.com/addyosmani/agent-skills"
    assert ocr.rejoin("curl https://imbo.dev/install\nUse it") == "curl https://imbo.dev/install\nUse it"
    assert ocr.rejoin("plain text/\nnext") == "plain text/\nnext"


def test_a_fallback_engine_is_recorded_on_the_capture(tmp_path: Path):
    store = Store(tmp_path / "d.db")
    media = tmp_path / "media"
    media.mkdir()
    (media / "AAA111.jpg").write_bytes(b"jpg")
    cid = _capture(store, "w:1", '"AAA111.jpg"')
    res = {"ok": True, "text": "nothing", "backend": "winocr", "engine_report": {"fallback": True, "reason": "indra: not installed"}}
    ocr.read_inbox(store, media, lambda p: res, repo_check=lambda r: True)
    declared = store.one("SELECT declared FROM captures WHERE id=?", (cid,))["declared"]["ocr"]
    assert declared["engine_fallback"] == "indra: not installed" and "blocks" not in declared
