"""darwin_read_posts: post text through Links, links inside become sources, a login wall stops and names the site."""
from darwin_hoard import social
from darwin_hoard.store import Store


def test_reads_posts_once_and_links_what_they_point_at(tmp_path):
    store = Store(tmp_path / "d.db")
    post = store.upsert_source(url="https://x.com/ann/status/123?a=zz")
    profile = store.upsert_source(url="https://x.com/ann")
    calls = []

    def call(app, tool, args, timeout=0):
        calls.append(args["url"])
        return {"ok": True, "result": {"site": "x", "author": "Ann @ann · 2h", "text": "New repo! microsoft/markitdown and/or more",
                                       "links": [{"href": "https://github.com/owner/tool"}, {"href": "https://x.com/someone"}, {"href": "https://blog.example.com/post"}]}}

    out = social.read_posts(store, call, repo_check=lambda r: r == "microsoft/markitdown")
    assert calls == ["https://x.com/ann/status/123"] and out["read"] == 1 and out["linked"] == 1
    keys = {r["key"] for r in store.q("SELECT key FROM sources")}
    assert {"repo:owner/tool", "repo:microsoft/markitdown", "url:https://blog.example.com/post"} <= keys
    assert "url:https://x.com/someone" not in keys and profile
    src = store.source(post)
    assert src["title"].startswith("Ann @ann: New repo!") and src["meta"]["post"]["refs"]
    assert social.read_posts(store, call)["read"] == 0 and len(calls) == 1


def test_login_wall_stops_and_names_the_site(tmp_path):
    store = Store(tmp_path / "d.db")
    store.upsert_source(url="https://instagram.com/p/abc/")
    out = social.read_posts(store, lambda *a, **k: {"ok": False, "error": "LOGIN_NEEDED", "result": {"code": "LOGIN_NEEDED", "site": "instagram"}})
    assert out["login_needed"] == "instagram" and out["remaining"] == 1
    assert len(social.pending(store)) == 1


def test_a_refusal_stops_without_marking_and_errors_are_retried(tmp_path):
    store = Store(tmp_path / "d.db")
    store.upsert_source(url="https://x.com/a/status/1")
    out = social.read_posts(store, lambda *a, **k: {"ok": False, "error": "X no dejó leer el post (HTTP ERROR 403).", "result": {"code": "REFUSED", "site": "x"}})
    assert out["login_needed"] == "x" and len(social.pending(store)) == 1
    out = social.read_posts(store, lambda *a, **k: {"ok": False, "error": "timeout", "result": {"code": "TIMEOUT"}})
    assert out["errors"] and len(social.pending(store)) == 1


def test_site_comes_from_the_url_when_the_error_does_not_say(tmp_path):
    store = Store(tmp_path / "d.db")
    store.upsert_source(url="https://x.com/a/status/1")
    out = social.read_posts(store, lambda *a, **k: {"ok": False, "status": 502, "error": "X (Twitter) no dejó leer el post (HTTP ERROR 403)."})
    assert out["login_needed"] == "x" and len(social.pending(store)) == 1
