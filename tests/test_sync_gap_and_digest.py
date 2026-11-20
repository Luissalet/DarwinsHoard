"""The chat gap Darwin leaves while stopped (caught up on start, named on the page) and the digest of the reels it reads."""
import time

from darwin_hoard import social
from darwin_hoard.services import Services
from darwin_hoard.store import Store

CHAT = "120363000000000000@g.us"
DAY = 86400


def _services(tmp_path, chat=CHAT):
    svc = Services.__new__(Services)
    svc.store = Store(tmp_path / "d.db")
    svc.settings = {"whatsapp_chat": chat, "whatsapp_chat_name": "Gittrend", "whatsapp_account": "test-account"}
    svc._sync_locks = {}
    svc._caught_up = False
    svc.start_ocr = lambda: None
    svc.start_posts = lambda: None
    return svc


def test_the_page_says_how_many_days_the_chat_has_gone_unread(tmp_path):
    svc = _services(tmp_path)
    svc.store.set_meta("whatsapp_last_sync", time.time() - 3.4 * DAY)
    got = svc.sync_status()
    assert got["configured"] and got["stale"] and 3.3 <= got["days_without_sync"] <= 3.5 and got["chat"] == "Gittrend"
    svc.store.set_meta("whatsapp_last_sync", time.time() - 3600)
    assert not svc.sync_status()["stale"]


def test_without_a_sync_the_newest_message_dates_the_gap(tmp_path):
    svc = _services(tmp_path)
    svc.store.add_capture(capture_key="w:1", channel="whatsapp", text="x", at=time.time() - 5 * DAY)
    assert 4.9 <= svc.sync_status()["days_without_sync"] <= 5.1
    assert _services(tmp_path / "other", chat="").sync_status()["configured"] is False


def test_start_up_reads_what_was_said_while_stopped_once(tmp_path):
    svc = _services(tmp_path)
    svc.store.set_meta("whatsapp_last_sync", time.time() - 2 * DAY)
    runs = []
    svc.sync_whatsapp = lambda **k: runs.append(1) or {"created": 7, "pass_complete": True}
    info = svc.catch_up_whatsapp()
    assert info["created"] == 7 and 1.9 <= info["gap_days"] <= 2.1 and svc.store.get_meta("whatsapp_catch_up")["created"] == 7
    assert svc.catch_up_whatsapp() is None and runs == [1]


def test_a_long_gap_goes_on_at_the_next_period_and_a_missing_chat_does_nothing(tmp_path):
    svc = _services(tmp_path)
    svc.sync_whatsapp = lambda **k: {"created": 200, "pass_complete": False}
    svc.catch_up_whatsapp()
    assert svc._caught_up is False
    quiet = _services(tmp_path / "q", chat="")
    quiet.sync_whatsapp = lambda **k: (_ for _ in ()).throw(AssertionError("no chat chosen"))
    assert quiet.catch_up_whatsapp() is None


# ---------------------------------------------------------------- reels

REEL = "https://instagram.com/reel/Cabc123/"


def _links(digest_body, calls):
    def call(app, tool, args, timeout=0):
        calls.append(tool)
        if tool == "read_post":
            return {"ok": True, "result": {"site": "instagram", "author": "ann", "text": "look at this #agents", "links": []}}
        assert tool == "video_digest" and args["url"].startswith("https://instagram.com/reel/") and args["level"] == "card"
        return digest_body
    return call


def test_a_read_reel_is_digested_and_the_card_becomes_its_summary(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(url=REEL)
    calls = []
    body = {"ok": True, "result": {"status": "done", "link_id": "L1", "text": "Card: a tour of microsoft/markitdown and https://github.com/owner/tool"}}
    out = social.read_posts(store, _links(body, calls), repo_check=lambda r: r == "microsoft/markitdown")
    assert calls == ["read_post", "video_digest"] and out["read"] == 1 and out["digested"] == 1
    src = store.source(sid)
    assert src["summary"].startswith("Card: a tour of microsoft/markitdown")
    digest = src["meta"]["video_digest"]
    assert digest["status"] == "done" and digest["caption"] == "look at this #agents" and digest["link_id"] == "L1"
    assert {"repo:microsoft/markitdown", "repo:owner/tool"} <= {r["key"] for r in store.q("SELECT key FROM sources")}
    assert sorted(out["found"]) == ["https://github.com/microsoft/markitdown", "https://github.com/owner/tool"]
    assert social.read_posts(store, _links(body, calls))["digested"] == 0 and calls == ["read_post", "video_digest"]


def test_reels_read_before_are_digested_on_the_next_pass_and_a_failure_is_retried_twice(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(url=REEL)
    calls = []
    social.read_posts(store, _links({"ok": True, "result": {"status": "failed", "error": "download needs sign-in"}}, calls))
    assert store.source(sid)["meta"]["video_digest"]["attempts"] == 1
    social.read_posts(store, _links({"ok": True, "result": {"status": "failed", "error": "again"}}, calls))
    social.read_posts(store, _links({"ok": True, "result": {"status": "done", "text": "never asked"}}, calls))
    assert calls.count("video_digest") == 2 and "video_digest" in store.source(sid)["meta"]
    assert social.pending_digests(store) == []


def test_a_digest_still_running_does_not_use_up_an_attempt(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(url=REEL)
    social.read_posts(store, _links({"ok": True, "result": {"status": "running"}}, []))
    assert store.source(sid)["meta"]["video_digest"]["attempts"] == 0 and social.pending_digests(store)


def test_a_post_that_is_not_a_video_is_not_digested_and_digest_can_be_turned_off(tmp_path):
    store = Store(tmp_path / "d.db")
    store.upsert_source(url="https://x.com/ann/status/1")
    calls = []
    social.read_posts(store, _links({"ok": True, "result": {"status": "done", "text": "x"}}, calls))
    assert calls == ["read_post"]
    store.upsert_source(url=REEL)
    social.read_posts(store, _links({"ok": True, "result": {"status": "done", "text": "x"}}, calls), digest=False)
    assert calls == ["read_post", "read_post"]


def test_an_unreachable_links_stops_the_digests_without_losing_the_reel(tmp_path):
    store = Store(tmp_path / "d.db")
    store.upsert_source(url=REEL)
    store.upsert_source(url="https://instagram.com/reel/Cdef456/")
    calls = []

    def call(app, tool, args, timeout=0):
        calls.append(tool)
        if tool == "read_post":
            return {"ok": True, "result": {"site": "instagram", "author": "a", "text": "t", "links": []}}
        return {"ok": False, "error": "hub not reachable", "status": 503}

    out = social.read_posts(store, call)
    assert calls.count("video_digest") == 1 and out["errors"] and len(social.pending_digests(store)) == 2
