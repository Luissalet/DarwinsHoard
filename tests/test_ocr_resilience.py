"""Screenshots without Kafka (start it, or read with vision) and links the picture cut or garbled (completed or not taken)."""
import time
from pathlib import Path

from darwin_hoard import ocr
from darwin_hoard.store import Store

DOWN = {"ok": False, "error": "kafka unreachable", "via": "kafka", "kind": "app_down"}


def _inbox(tmp_path, *names):
    store = Store(tmp_path / "d.db")
    media = tmp_path / "media"
    media.mkdir()
    for n, name in enumerate(names):
        (media / name).write_bytes(b"png")
        store.add_capture(capture_key=f"w:{n}", channel="whatsapp", text="", attachment=f'"{name}"', at=time.time())
    return store, media


# ---------------------------------------------------------------- Kafka stopped

def test_a_stopped_kafka_is_started_and_the_picture_read_again():
    seen, started = [], []

    def engine(path):
        seen.append(path)
        return DOWN if len(seen) == 1 else {"ok": True, "text": "microsoft/markitdown", "backend": "kafka"}

    read = ocr.chain(engine, start_app=lambda: started.append(1) or True, vision=lambda p: {"ok": False, "error": "must not be used"})
    res = read("a.png")
    assert res["ok"] and res["backend"] == "kafka" and len(seen) == 2 and started == [1]


def test_without_kafka_the_vision_model_reads_the_picture():
    read = ocr.chain(lambda p: DOWN, start_app=lambda: False,
                     vision=lambda p: {"ok": True, "text": "see github.com/microsoft/markitdown", "backend": "vision:glm"})
    res = read("a.png")
    assert res["ok"] and res["backend"] == "vision:glm"
    assert res["engine_report"]["fallback"] and "kafka unreachable" in res["engine_report"]["reason"]


def test_an_unreadable_picture_is_not_sent_anywhere_else():
    bad = {"ok": False, "error": "not an image", "via": "kafka", "kind": "tool_error"}
    called = []
    read = ocr.chain(lambda p: bad, start_app=lambda: called.append("start") or True, vision=lambda p: called.append("vision") or {"ok": True})
    assert read("a.png") is bad and called == []


def test_when_nothing_reads_it_the_error_names_every_attempt(tmp_path):
    store, media = _inbox(tmp_path, "AAA111.png")
    read = ocr.chain(lambda p: DOWN, start_app=lambda: False, vision=lambda p: {"ok": False, "error": "no_model", "kind": "vision"})
    out = ocr.read_inbox(store, media, read)
    assert "kafka unreachable" in out["error"] and "vision: no_model" in out["error"] and out["remaining"] == 1
    assert not store.q("SELECT 1 FROM captures WHERE declared LIKE '%ocr%'")


def test_a_fallback_read_is_recorded_on_the_capture(tmp_path):
    store, media = _inbox(tmp_path, "AAA111.png")
    read = ocr.chain(lambda p: DOWN, vision=lambda p: {"ok": True, "text": "github.com/microsoft/markitdown", "backend": "vision:glm"})
    out = ocr.read_inbox(store, media, read, repo_check=lambda r: True)
    assert out["read"] == 1 and out["found"] == ["https://github.com/microsoft/markitdown"]
    declared = store.q("SELECT declared FROM captures")[0]["declared"]["ocr"]
    assert declared["backend"] == "vision:glm" and "kafka unreachable" in declared["engine_fallback"]


# ---------------------------------------------------------------- links the picture cut or garbled

OWNER = {"NousResearch": ["atropos", "hermes-official-plugins", "psyche"]}


def _read(tmp_path, text, *, exists, search=None, owners=OWNER):
    store, media = _inbox(tmp_path, "AAA111.png")
    out = ocr.read_inbox(store, media, lambda p: {"ok": True, "text": text, "backend": "fake"},
                         repo_check=lambda r: exists(r), repo_list=lambda o: owners.get(o), repo_search=search)
    declared = store.q("SELECT declared FROM captures")[0]["declared"]["ocr"]
    return store, out, declared


def _keys(store):
    return {r["key"] for r in store.q("SELECT key FROM sources")}


def test_a_name_the_picture_cut_is_completed_from_the_owners_repositories(tmp_path):
    exists = lambda r: r == "NousResearch/hermes-official-plugins"
    store, out, declared = _read(tmp_path, "new: NousResearch/hern", exists=exists)
    assert _keys(store) == {"repo:nousresearch/hermes-official-plugins"}
    assert declared["completed"] == ["NousResearch/hermes-official-plugins"] and not declared["unverified"]


def test_a_cut_link_is_checked_like_a_bare_name(tmp_path):
    exists = lambda r: r == "NousResearch/hermes-official-plugins"
    store, out, declared = _read(tmp_path, "https://github.com/NousResearch/hern", exists=exists)
    assert _keys(store) == {"repo:nousresearch/hermes-official-plugins"}
    assert out["found"] == ["https://github.com/NousResearch/hermes-official-plugins"]


def test_a_cut_raw_link_becomes_its_repository(tmp_path):
    exists = lambda r: r == "NousResearch/hermes-official-plugins"
    store, out, _ = _read(tmp_path, "https://raw.githubusercontent.com/NousResearch/hermes-official-plug", exists=exists)
    assert _keys(store) == {"repo:nousresearch/hermes-official-plugins"}


def test_two_repositories_that_fit_are_no_answer_and_nothing_is_created(tmp_path):
    owners = {"NousResearch": ["hermes-agent", "hermes-official-plugins"]}
    store, out, declared = _read(tmp_path, "https://github.com/NousResearch/herm", exists=lambda r: False, owners=owners)
    assert _keys(store) == set() and declared["unverified"] == ["NousResearch/herm"] and out["linked"] == 0


def test_a_link_github_denies_is_not_a_source_but_other_links_stay(tmp_path):
    store, out, declared = _read(tmp_path, "https://github.com/nobody/nothing and https://blog.example.com/post", exists=lambda r: False)
    assert _keys(store) == {"url:https://blog.example.com/post"} and declared["unverified"] == ["nobody/nothing"]


def test_when_github_cannot_be_asked_a_link_is_kept_but_marked(tmp_path):
    store, out, _ = _read(tmp_path, "https://github.com/some/repo", exists=lambda r: None)
    src = store.q("SELECT key, meta FROM sources")[0]
    assert src["key"] == "repo:some/repo" and src["meta"]["github_verified"] is False


def test_a_bare_name_nobody_confirms_stays_out_as_before(tmp_path):
    store, out, declared = _read(tmp_path, "and/or something", exists=lambda r: None)
    assert _keys(store) == set() and declared["unverified"] == ["and/or"]


def test_github_search_completes_owners_with_many_repositories(tmp_path):
    asked = []

    def search(owner, word):
        asked.append((owner, word))
        return ["hermes-official-plugins"]

    exists = lambda r: r == "NousResearch/hermes-official-plugins"
    store, out, _ = _read(tmp_path, "NousResearch/hermes-off", exists=exists, search=search, owners={"NousResearch": []})
    assert asked == [("NousResearch", "hermes-off")] and _keys(store) == {"repo:nousresearch/hermes-official-plugins"}


def test_letters_the_engine_mixes_up_still_find_the_repository():
    got = ocr.complete_repo("NousResearch/hern", lambda o: ["atropos", "hermes-official-plugins"])
    assert got == "NousResearch/hermes-official-plugins"
    assert ocr.complete_repo("a/xy", lambda o: ["xyz"]) is None          # too short to guess from
