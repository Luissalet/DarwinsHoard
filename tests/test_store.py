from __future__ import annotations

import pytest

from darwin_hoard.canon import canonical_url, extract_refs, repo_key, source_key
from darwin_hoard.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "darwin.db")
    yield s
    s.close()


def test_canonical_url_strips_tracking_and_collapses_github():
    assert canonical_url("http://www.Example.com/a/?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
    assert canonical_url("https://github.com/Owner/Repo/tree/main/src?tab=readme-ov-file") == "https://github.com/Owner/Repo"
    assert canonical_url("github.com/owner/repo.git") == "https://github.com/owner/repo"
    assert canonical_url("https://youtube.com/watch?v=abc&si=zz") == "https://youtube.com/watch?v=abc"


def test_repo_and_source_keys():
    assert repo_key("https://github.com/Owner/Repo/blob/x.py") == "repo:owner/repo"
    assert repo_key("owner/repo") == "repo:owner/repo"
    assert repo_key("https://github.com/topics/ai") is None
    assert source_key(url="https://news.site/post/1?utm_x=1") == "url:https://news.site/post/1"
    assert source_key(title="  Una  idea ").startswith("idea:")


def test_extract_refs_dedupes_urls_and_candidates():
    refs = extract_refs("mira https://github.com/a/b?tab=x y también a/b y foo-org/bar_baz, no 3/4")
    keys = {r["key"] for r in refs}
    assert keys == {"repo:a/b", "repo:foo-org/bar_baz"}


def test_source_upsert_is_idempotent_and_keeps_existing(store):
    a = store.upsert_source(url="https://github.com/A/B", title="", legacy_radar_no=12)
    b = store.upsert_source(repo="a/b", title="New title", summary="s")
    assert a == b
    row = store.source(a)
    assert row["legacy_radar_no"] == 12 and row["summary"] == "s"
    assert store.counts()["sources"] == 1


def test_renamed_repo_merges_by_github_id(store):
    a = store.upsert_source(repo="old/name", github_id=99)
    b = store.upsert_source(repo="new/name", github_id=99)
    assert a == b
    assert store.source_by_key("repo:new/name")["id"] == a


def test_capture_idempotent_and_counted(store):
    sid = store.upsert_source(repo="a/b")
    c1, new1 = store.add_capture(capture_key="radar:file:1", channel="radar", text="x", source_id=sid)
    c2, new2 = store.add_capture(capture_key="radar:file:1", channel="radar", text="x", source_id=sid)
    assert c1 == c2 and new1 and not new2
    assert store.source(sid)["captures"] == 1


def test_state_changes_keep_history(store):
    sid = store.upsert_source(repo="a/b")
    pid = store.upsert_proposal(key="p1", source_id=sid, target="faustus", state="pendiente", origin="radar")
    store.upsert_proposal(key="p1", source_id=sid, target="faustus", state="aceptada", origin="tracker")
    assert store.one("SELECT state FROM proposals WHERE id=?", (pid,))["state"] == "aceptada"
    # a weaker origin does not override
    store.upsert_proposal(key="p1", source_id=sid, state="pendiente", origin="mention")
    assert store.one("SELECT state FROM proposals WHERE id=?", (pid,))["state"] == "aceptada"
    hist = store.history_of("proposals", pid)
    assert [(h["old"], h["new"]) for h in hist] == [("pendiente", "aceptada")]
    with pytest.raises(ValueError):
        store.set_state("proposals", pid, "state", "hecho")


def test_social_links_drop_share_parameters_and_old_keys_merge(tmp_path):
    from darwin_hoard.canon import canonical_url
    from darwin_hoard.store import Store
    assert canonical_url("https://x.com/tom_doerr/status/2115405924646985924?a=mM_LjFRDSf") == "https://x.com/tom_doerr/status/2115405924646985924"
    assert canonical_url("https://twitter.com/tom_doerr/status/1?s=20&t=abc") == "https://x.com/tom_doerr/status/1"
    assert canonical_url("https://www.youtube.com/watch?v=abc&si=x") == "https://youtube.com/watch?v=abc"
    store = Store(tmp_path / "d.db")
    with store.tx() as c:  # two sources keyed before the rule existed
        for key in ("url:https://x.com/u/status/9?a=one", "url:https://x.com/u/status/9?a=two"):
            c.execute("INSERT INTO sources(key, kind, url, title, first_seen, last_seen, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                      (key, "article", key[4:], key, 1, 2, 1, 1))
    first = store.one("SELECT id FROM sources WHERE key=?", ("url:https://x.com/u/status/9?a=one",))["id"]
    cid, _ = store.add_capture(capture_key="k1", channel="whatsapp", text="t")
    store.link_capture(cid, first)
    assert store.recanonicalize() == {"renamed": 1, "merged": 1}
    rows = store.q("SELECT id, key FROM sources")
    assert [r["key"] for r in rows] == ["url:https://x.com/u/status/9"]
    assert store.source_by_key("url:https://x.com/u/status/9?a=two")["id"] == rows[0]["id"]
    assert store.q("SELECT source_id FROM capture_sources")[0]["source_id"] == rows[0]["id"]
    assert store.recanonicalize() == {"renamed": 0, "merged": 0}
