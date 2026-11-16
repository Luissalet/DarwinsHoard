"""A discovery the OCR garbled can be marked as the correction of the real one: nothing is lost and it stops showing as «sin propuesta»."""
import pytest

from darwin_hoard import agent_tools, query
from darwin_hoard.errors import DarwinError
from darwin_hoard.services import Services
from darwin_hoard.store import Store


def _pair(tmp_path):
    store = Store(tmp_path / "d.db")
    wrong = store.upsert_source(repo="NousResearch/hern", title="NousResearch/hern", summary="cut by the screenshot")
    right = store.upsert_source(repo="NousResearch/hermes-official-plugins", title="Hermes plugins")
    cap_w, _ = store.add_capture(capture_key="w:1", channel="whatsapp", text="NousResearch/hern")
    store.link_capture(cap_w, wrong)
    cap_r, _ = store.add_capture(capture_key="w:2", channel="whatsapp", text="full name")
    store.link_capture(cap_r, right)
    return store, wrong, right, cap_w


def test_the_wrong_source_folds_into_the_right_one(tmp_path):
    store, wrong, right, cap_w = _pair(tmp_path)
    store.upsert_proposal(key="repo:nousresearch/hermes-official-plugins->hermes", source_id=right, target="hermes", reason="plugins")
    assert wrong in {r["id"] for r in query.find(store, state="sin_propuesta", limit=50)["items"]}
    out = store.correct_source(wrong, right, by="luis", note="OCR cut the name")
    assert out["corrected"] == wrong and store.source(wrong) is None
    assert store.one("SELECT source_id FROM captures WHERE id=?", (cap_w,))["source_id"] == right
    assert store.one("SELECT COUNT(*) AS n FROM capture_sources WHERE source_id=?", (right,))["n"] == 2
    assert store.source(right)["captures"] == 2
    assert store.source_by_key("repo:nousresearch/hern")["id"] == right          # the old key still lands
    meta = store.source(right)["meta"]["corrections"][0]
    assert meta["key"] == "repo:nousresearch/hern" and meta["summary"] == "cut by the screenshot" and meta["by"] == "luis"
    assert store.history_of("sources", right)[0]["field"] == "correction"
    assert wrong not in {r["id"] for r in query.find(store, state="sin_propuesta", limit=50)["items"]}


def test_proposals_and_deliveries_of_the_wrong_one_move_with_it(tmp_path):
    store, wrong, right, _ = _pair(tmp_path)
    p = store.upsert_proposal(key="repo:nousresearch/hern->hermes", source_id=wrong, target="hermes", reason="from the cut name")
    store.upsert_delivery(key="d1", source_id=wrong, target="hermes", proposal_id=p, repo="Hermes's Hoard", commit_sha="abc1234")
    out = store.correct_source(wrong, right)
    assert out["moved"] == {"proposals": 1, "deliveries": 1, "captures": 1} and out["proposals_folded"] == 0
    assert store.one("SELECT source_id FROM proposals WHERE id=?", (p,))["source_id"] == right
    assert store.one("SELECT source_id FROM deliveries WHERE key='d1'")["source_id"] == right


def test_two_proposals_for_the_same_app_keep_the_right_ones_and_the_history_of_both(tmp_path):
    store, wrong, right, _ = _pair(tmp_path)
    keep = store.upsert_proposal(key="repo:nousresearch/hermes-official-plugins->hermes", source_id=right, target="hermes", state="aceptada", origin="luis")
    dup = store.upsert_proposal(key="repo:nousresearch/hern->hermes", source_id=wrong, target="hermes")
    store.set_state("proposals", dup, "state", "investigando", by="agent")
    did = store.upsert_delivery(key="d1", source_id=wrong, target="hermes", proposal_id=dup, commit_sha="abc1234")
    out = store.correct_source(wrong, right)
    assert out["proposals_folded"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM proposals WHERE target='hermes'")["n"] == 1
    assert store.one("SELECT proposal_id FROM deliveries WHERE id=?", (did,))["proposal_id"] == keep
    assert [h["new"] for h in store.history_of("proposals", keep)] == ["investigando"]


def test_it_refuses_nonsense(tmp_path):
    store, wrong, right, _ = _pair(tmp_path)
    with pytest.raises(ValueError):
        store.correct_source(wrong, wrong)
    with pytest.raises(KeyError):
        store.correct_source(wrong, 9999)


def test_the_tool_is_in_the_catalogue_and_answers_with_the_genealogy(tmp_path):
    store, wrong, right, _ = _pair(tmp_path)
    assert "darwin_source_correct" in {t["name"] for t in agent_tools.tool_catalog()}
    svc = Services.__new__(Services)
    svc.store = store
    svc.skill_impacts = lambda **k: {}
    got = agent_tools.call_tool(svc, "darwin_source_correct", {"source_id": wrong, "into_id": right, "note": "ocr", "by": "luis"})
    assert got["corrected"] == wrong and got["source"]["source"]["id"] == right
    with pytest.raises(DarwinError):
        agent_tools.call_tool(svc, "darwin_source_correct", {"source_id": wrong, "into_id": right})
