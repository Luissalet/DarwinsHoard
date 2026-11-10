"""Ãgora tasks opened from Darwin's own proposals (Â«â€¦ (Darwin 1013)Â») link back to them and record their commits as deliveries."""
from darwin_hoard.legacy import LegacyImporter, darwin_proposal_refs
from darwin_hoard.store import Store


def test_refs_read_one_or_several_proposals_from_the_title():
    assert darwin_proposal_refs("Paneles propios (Darwin 1013)") == [1013]
    assert darwin_proposal_refs("GalerÃ­as y Flexoki (Darwin 1016, 1046)") == [1016, 1046]
    assert darwin_proposal_refs("Cerebro (Darwin 1031, 1032, 1042)") == [1031, 1032, 1042]
    assert darwin_proposal_refs("Darwin's Hoard: arreglar el OCR") == []


def test_a_done_task_links_its_proposal_and_records_each_commit(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="owner/tool", title="owner/tool", kind="repo", key="repo:owner/tool")
    pid = store.upsert_proposal(key="repo:owner/tool->faustus", source_id=sid, target="faustus", state="aceptada", origin="agent")
    imp = LegacyImporter(store)
    open_task = {"id": 77, "title": f"Algo (Darwin {pid})", "status": "claimed", "commits": []}
    assert imp._link_proposals([pid], "faustus", open_task) == 0
    row = store.one("SELECT agora_space, agora_task FROM proposals WHERE id=?", (pid,))
    assert (row["agora_space"], row["agora_task"]) == ("faustus", 77)
    done = dict(open_task, status="done", commits=["abc1234", "def5678"])
    assert imp._link_proposals([pid], "faustus", done) == 2
    assert imp._link_proposals([pid], "faustus", done) == 2          # idempotent: same keys, no duplicates
    rows = store.q("SELECT commit_sha, repo, implementation, agora_task FROM deliveries WHERE proposal_id=? ORDER BY commit_sha", (pid,))
    assert [(r["commit_sha"], r["repo"], r["implementation"], r["agora_task"]) for r in rows] == [
        ("abc1234", "faustus", "integrada", 77), ("def5678", "faustus", "integrada", 77)]
    assert imp._link_proposals([999999], "faustus", done) == 0        # unknown proposal: nothing
