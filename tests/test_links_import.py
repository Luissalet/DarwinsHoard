"""darwin_import_links: tagged links and GitHub repositories only, idempotent, titles never guessed as repos."""
from darwin_hoard import links_import
from darwin_hoard.store import Store


def test_imports_tagged_links_and_repositories_once(tmp_path):
    store = Store(tmp_path / "d.db")
    pages = {
        "darwin": [{"id": "a", "url": "https://blog.example.com/post?utm_source=x", "title": "and/or thoughts", "tags": ["darwin"]}],
        "github.com": [{"id": "b", "url": "https://github.com/owner/tool/tree/main", "title": "tool", "tags": []},
                       {"id": "c", "url": "https://github.com/someone", "title": "a profile", "tags": []}],
    }

    def call(app, tool, args, timeout=0):
        key = args.get("tag") or args.get("site")
        return {"ok": True, "result": {"items": pages[key], "next_cursor": None}}

    out = links_import.import_links(store, call)
    keys = {r["key"] for r in store.q("SELECT key FROM sources")}
    assert keys == {"url:https://blog.example.com/post", "repo:owner/tool"}
    assert out["created"] == 2 and out["links_read"] == 3
    assert links_import.import_links(store, call)["created"] == 0
    assert store.one("SELECT title FROM sources WHERE key='url:https://blog.example.com/post'")["title"] == "and/or thoughts"
