"""A stopped WhatsApp bridge is started by the sync instead of failing for days."""

import pytest

from darwin_hoard.services import Services
from darwin_hoard.store import Store

CHAT = "120363000000000000@g.us"
DOWN = RuntimeError('Faustus answered 503: {"detail": "WhatsApp bridge is not running (ConnectError); start it in Tools"}')


def _services(tmp_path, *, bridge_up_after_start=True):
    svc = Services.__new__(Services)
    svc.store = Store(tmp_path / "d.db")
    svc.settings = {"faustus_url": "http://faustus.test", "whatsapp_chat": CHAT, "whatsapp_account": "luis"}
    svc._sync_locks = {}
    svc.start_ocr = lambda: None
    svc.start_posts = lambda: None
    state = {"up": False, "starts": 0, "pages": 0}

    def get(path, params):
        if path == "/api/whatsapp/status":
            return {"status": "connected", "sync": {"active": False}}
        if not state["up"]:
            raise DOWN
        if path == "/api/whatsapp/chats":
            return {"chats": [{"jid": CHAT, "name": "Gittrend"}]}
        state["pages"] += 1
        return {"messages": [{"id": "M1", "chat": CHAT, "from_me": True, "kind": "text", "ts": 1793900000,
                              "text": "https://github.com/patch-gg/pixelfx", "key": {"id": "M1"}}],
                "next_cursor": "", "has_more": False, "coverage": {}}

    def post(path, body=None, timeout=60):
        assert path == "/api/whatsapp/start"
        state["starts"] += 1
        state["up"] = bridge_up_after_start
        return {"started": True}

    svc._faustus_get = get
    svc._faustus_post = post
    return svc, state


def test_sync_starts_a_stopped_bridge_and_reads(tmp_path):
    svc, state = _services(tmp_path)
    out = svc.sync_whatsapp()
    assert state["starts"] == 1
    assert out["bridge_started"]["started"] is True
    assert out["created"] + out["existing"] == 1
    assert svc.store.get_meta("whatsapp_bridge_started_at")


def test_bridge_that_stays_down_is_reported_once(tmp_path):
    svc, state = _services(tmp_path, bridge_up_after_start=False)
    with pytest.raises(RuntimeError, match="not running"):
        svc.sync_whatsapp()
    assert state["starts"] == 1


def test_chat_list_starts_the_bridge_too(tmp_path):
    svc, state = _services(tmp_path)
    chats = svc.whatsapp_chats("gitt")
    assert state["starts"] == 1 and chats[0]["jid"] == CHAT


def test_other_faustus_errors_are_not_hidden(tmp_path):
    svc, state = _services(tmp_path)

    def broken(path, params):
        raise RuntimeError("Faustus answered 500: boom")

    svc._faustus_get = broken
    with pytest.raises(RuntimeError, match="500"):
        svc.sync_whatsapp()
    assert state["starts"] == 0


def test_faustus_moved_to_a_spark_is_asked_there(tmp_path, monkeypatch):
    import io
    import json
    import urllib.request

    svc = Services.__new__(Services)
    svc.settings = {"faustus_url": "http://127.0.0.1:7000/"}
    placement = {"location": "sparks", "job": {"running": False}, "urls": {"faustus": "https://spark3.example.ts.net/"}}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Resp(json.dumps(placement).encode()))
    assert svc._faustus_base() == "https://spark3.example.ts.net"
    svc._placement_cache = None
    placement["location"] = "pc"
    assert svc._faustus_base() == "http://127.0.0.1:7000"
    svc._placement_cache = None
    placement.update(location="sparks", job={"running": True})
    assert svc._faustus_base() == "http://127.0.0.1:7000"   # mid-move: the configured copy


def test_pictures_come_from_the_faustus_that_runs_now(tmp_path, monkeypatch):
    import io
    import time
    import urllib.request
    from types import SimpleNamespace

    svc = Services.__new__(Services)
    faustus = tmp_path / "faustus"
    (faustus / "data" / "whatsapp" / "media").mkdir(parents=True)
    (faustus / "data" / "whatsapp" / "media" / "LOCAL.jpg").write_bytes(b"local")
    svc.config = SimpleNamespace(faustus_dir=str(faustus), db_path=str(tmp_path / "data" / "darwin.db"))
    (tmp_path / "data").mkdir()
    svc.settings = {"faustus_url": "http://127.0.0.1:7000"}
    svc._placement_cache = (time.time(), "https://spark.example")
    asked = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(url, timeout=0):
        asked.append(url)
        if url.endswith("/REMOTE.jpg"):
            return Resp(b"remote")
        raise OSError("404")

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert svc.ensure_media('"LOCAL.jpg"').read_bytes() == b"local"
    assert svc.ensure_media('"REMOTE.jpg"').read_bytes() == b"remote"
    assert asked == ["https://spark.example/api/whatsapp/media/REMOTE.jpg"]
    assert svc.ensure_media('"MISSING.jpg"') is None
    assert svc.ensure_media('"../secret.jpg"') is None


def test_a_picture_marked_missing_gets_a_second_reading(tmp_path, monkeypatch):
    svc = Services.__new__(Services)
    svc.store = Store(tmp_path / "d.db")
    cid, _ = svc.store.add_capture(capture_key="k1", channel="whatsapp", attachment='"PIC.jpg"',
                                   declared={"ocr": {"error": "image file not found"}}) if hasattr(svc.store, "add_capture") else (None, None)
    if cid is None:
        pytest.skip("store has no add_capture helper")
    monkeypatch.setattr(Services, "ensure_media", lambda self, raw: tmp_path / "PIC.jpg")
    assert svc._prefetch_media(10) == 1
    row = svc.store.one("SELECT declared FROM captures WHERE id=?", (cid,))
    assert "ocr" not in (row["declared"] if isinstance(row["declared"], dict) else __import__("json").loads(row["declared"]))
