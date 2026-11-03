"""Suits: status from a capability fixture, backing refused without evidence, stale gaps, evaluation import."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from darwin_hoard import backing, reconcile, suit_seeds, suits
from darwin_hoard.config import Config
from darwin_hoard.errors import DarwinError
from darwin_hoard.main import create_app
from darwin_hoard.store import Store

EV = [{"kind": "test", "ref": "tests/test_x.py::test_works"}]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "d.db")
    now = time.time()
    with s.tx() as c:
        for key, level, name, app in [("faustus", "root", "Faustus", "faustus"), ("hoardhub", "hub", "Hoard Hub", "hoardhub"),
                                      ("app:ocr", "app", "Ocr's Hoard", "ocr"), ("cap:ocr:ocr", "capability", "ocr", "ocr"),
                                      ("tool:ocr:read_screenshot", "tool", "read_screenshot", "ocr"),
                                      ("cap:maps:3d-maps", "capability", "3d maps", "maps"), ("tool:maps:make_map", "tool", "make_map", "maps")]:
            c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, since, seen) VALUES (?,?,?,?,?,?,?)",
                      (key, None, level, name, app, now, now))
    yield s
    s.close()


def _suit(store, slug="job", ops=None):
    return suits.save_suit(store, {"slug": slug, "name": "Job", "objective": "x", "operations": ops if ops is not None else [
        {"name": "read", "capability_key": "tool:ocr:read_screenshot"}, {"name": "map", "capability_key": "tool:maps:make_map"},
        {"name": "new thing", "capability_key": ""}]})


def test_status_proposed_partial_backed_from_a_capability_fixture(store):
    _suit(store)
    got = suits.get_suit(store, "job")
    # both nodes exist in the tree, but nobody proved them: the names alone prove nothing
    assert got["status"] == "proposed"
    assert got["state"]["unproven"] == ["read", "map"] and got["state"]["missing"] == ["new thing"]
    backing.mark(store, "tool:ocr:read_screenshot", implemented=True, evidence=EV)
    assert suits.get_suit(store, "job")["status"] == "partial"
    backing.mark(store, "tool:maps:make_map", implemented=True, evidence=[{"kind": "commit", "ref": "abc1234"}])
    still = suits.get_suit(store, "job")
    assert still["status"] == "partial" and still["state"]["missing"] == ["new thing"]  # the missing capability keeps it partial
    suits.save_suit(store, {"slug": "job", "operations": [{"name": "read", "capability_key": "tool:ocr:read_screenshot"},
                                                           {"name": "map", "capability_key": "tool:maps:make_map"}]})
    done = suits.get_suit(store, "job")
    assert done["status"] == "backed" and done["state"]["backed"] == 2
    assert [o["state"] for o in done["state"]["operations"]] == ["backed", "backed"]
    assert suits.list_suits(store)["counts"] == {"proposed": 0, "partial": 0, "backed": 1, "evaluated": 0}


def test_an_optional_missing_operation_does_not_block_backing(store):
    backing.mark(store, "tool:ocr:read_screenshot", implemented=True, evidence=EV)
    _suit(store, ops=[{"name": "read", "capability_key": "tool:ocr:read_screenshot"}, {"name": "nice", "capability_key": "", "required": False}])
    assert suits.get_suit(store, "job")["status"] == "backed"


def test_a_node_missing_from_the_tree_is_missing_even_with_a_stale_backing_row(store):
    backing.mark(store, "tool:ocr:read_screenshot", implemented=True, evidence=EV)
    with store.tx() as c:
        c.execute("DELETE FROM capabilities WHERE key='tool:ocr:read_screenshot'")
    _suit(store, ops=[{"name": "read", "capability_key": "tool:ocr:read_screenshot"}])
    got = suits.get_suit(store, "job")
    assert got["status"] == "proposed" and got["state"]["missing"] == ["read"]


def test_backing_is_refused_without_evidence(store):
    for bad in (None, [], [{"kind": "commit", "ref": ""}], [{"kind": "commit", "ref": "not a hash"}], [{"kind": "claim", "ref": "x"}],
                [{"kind": "test", "ref": "works"}], ["abc1234"]):
        with pytest.raises(DarwinError) as e:
            backing.mark(store, "cap:ocr:ocr", implemented=True, evidence=bad)
        assert e.value.code == "invalid"
    assert backing.backing_of(store, "cap:ocr:ocr") is None
    with pytest.raises(DarwinError):
        backing.mark(store, "cap:nope", implemented=True, evidence=EV)
    # a row somebody wrote by hand without evidence is not trusted either
    with store.tx() as c:
        c.execute("INSERT INTO capability_backing(capability_key, evidence) VALUES ('cap:ocr:ocr', '[]')")
    _suit(store, ops=[{"name": "ocr", "capability_key": "cap:ocr:ocr"}])
    assert suits.get_suit(store, "job")["state"]["operations"][0]["state"] == "unproven"


def test_unmarking_removes_the_proof_and_keeps_history(store):
    backing.mark(store, "cap:ocr:ocr", implemented=True, evidence=EV)
    assert backing.mark(store, "cap:ocr:ocr", implemented=False)["changed"] is True
    assert backing.backing_of(store, "cap:ocr:ocr") is None
    assert len(store.q("SELECT * FROM history WHERE entity='capability_backing'")) == 2


def test_stale_gap_is_flagged_with_evidence_not_counted_open_and_listed(store):
    g1 = store.add_gap(title="Leer capturas de pantalla con OCR", target="ocr")
    g2 = store.add_gap(title="Hacer mapas 3D de ciudades", target="maps")
    g3 = store.add_gap(title="Detectar contradicciones", target="")
    g4 = store.add_gap(title="Nombrada a mano", target="maps", capability_key="tool:maps:make_map")
    assert reconcile.reconcile(store)["stale_count"] == 0  # nothing proved yet: a name is not evidence
    assert reconcile.listing(store)["open"] == 4
    backing.mark(store, "cap:ocr:ocr", implemented=True, evidence=EV, note="ok")
    backing.mark(store, "tool:maps:make_map", implemented=True, evidence=[{"kind": "qa_file", "ref": "docs/qa-2026-11-03.md"}])
    out = reconcile.reconcile(store)
    ids = {g["id"]: g for g in out["possibly_stale"]}
    assert set(ids) == {g1, g4}  # 'make_map' words are not in the text of g2; the explicit key flags g4
    assert ids[g1]["evidence"] == EV and ids[g1]["capability_key"] == "cap:ocr:ocr" and ids[g1]["reason"] == "name_match"
    assert ids[g4]["reason"] == "capability_key"
    assert out["open"] == 2 and out["total_marked_open"] == 4
    assert store.one("SELECT state FROM gaps WHERE id=?", (g1,))["state"] == "abierta"  # never closed by itself
    # the open count used by the rest of the app leaves them out
    from darwin_hoard.store import OPEN_GAP_SQL
    assert {r["id"] for r in store.q("SELECT id FROM gaps WHERE " + OPEN_GAP_SQL)} == {g2, g3}
    # a gap for another app is not answered by this app's capability
    store.add_gap(title="Leer capturas de pantalla con OCR", target="maps")
    assert len(reconcile.reconcile(store)["possibly_stale"]) == 2


def test_confirm_dismiss_and_proof_removed(store):
    g1 = store.add_gap(title="OCR de capturas", target="ocr")
    g2 = store.add_gap(title="Quiero OCR otra vez", target="ocr")
    backing.mark(store, "cap:ocr:ocr", implemented=True, evidence=EV)
    assert len(reconcile.reconcile(store)["possibly_stale"]) == 2
    out = reconcile.reconcile(store, confirm_ids=[g1], dismiss_ids=[g2])
    assert out["confirmed"] == [g1] and out["dismissed"] == [g2]
    assert store.one("SELECT state FROM gaps WHERE id=?", (g1,))["state"] == "resuelta"
    assert out["stale_count"] == 0 and out["open"] == 1  # g2 stays open and is not flagged again
    assert reconcile.reconcile(store)["stale_count"] == 0
    g3 = store.add_gap(title="OCR en facturas", target="ocr")
    assert reconcile.reconcile(store)["possibly_stale"][0]["id"] == g3
    backing.mark(store, "cap:ocr:ocr", implemented=False)
    assert reconcile.reconcile(store)["stale_count"] == 0 and reconcile.listing(store)["open"] == 2


def test_seeds_are_six_idempotent_and_honest(store):
    assert suit_seeds.seed(store)["added"] == 6
    assert suit_seeds.seed(store)["added"] == 0
    listing = suits.list_suits(store)
    assert listing["total"] == 6 and listing["counts"]["backed"] == 0 and listing["counts"]["evaluated"] == 0
    got = suits.get_suit(store, "repository-intake")
    assert got["objective"] and got["inputs"] and got["acceptance"] and got["recipe"] and got["judgement"] and got["views"] and got["concepts"]
    assert any(o["state"] == "missing" and o["missing_reason"] for o in got["state"]["operations"])
    suits.delete_suit(store, "repository-intake")
    assert suit_seeds.seed(store)["added"] == 0  # a deleted seed stays deleted
    with pytest.raises(DarwinError):
        suits.get_suit(store, "repository-intake")


def test_suit_validation(store):
    with pytest.raises(DarwinError):
        suits.save_suit(store, {"slug": "Bad Slug", "name": "x"})
    with pytest.raises(DarwinError):
        suits.save_suit(store, {"slug": "no-name"})
    with pytest.raises(DarwinError):
        suits.save_suit(store, {"slug": "ops-bad", "name": "x", "operations": [{"capability_key": "k"}]})


def _payload(slug="job", **over):
    p = {"format": suits.EVAL_FORMAT, "suit": slug, "evaluation_id": "ev1", "cases_scored": 3,
         "excluded": [{"case": "c0", "reason": "used_for_building"}],
         "aggregate": {"generic": {"cases": 3, "success_rate": 0.33}, "current": {"cases": 3, "success_rate": 0.66},
                       "candidate": {"cases": 3, "success_rate": 1.0}}}
    p.update(over)
    return p


def test_importing_results_makes_the_suit_evaluated_and_remembers_the_backing(store):
    _suit(store)
    assert suits.get_suit(store, "job")["status"] == "proposed"
    out = suits.import_evaluation(store, _payload())
    got = out["suit"]
    assert got["status"] == "evaluated"
    assert got["state"]["backing"] == "proposed"  # evaluated does not hide that nothing is backed
    assert got["evaluation"]["backing_at_import"]["missing"] == ["new thing"]
    assert got["evaluation"]["excluded"][0]["case"] == "c0" and got["evaluation"]["arms"] == ["candidate", "current", "generic"]
    assert suits.list_suits(store, "evaluated")["suits"][0]["slug"] == "job"
    again = suits.import_evaluation(store, _payload())
    assert again["replaced"] is True and store.one("SELECT COUNT(*) AS n FROM suit_evaluations")["n"] == 1
    suits.import_evaluation(store, _payload(evaluation_id="ev2"))
    assert store.one("SELECT COUNT(*) AS n FROM suit_evaluations")["n"] == 2


@pytest.mark.parametrize("change", [{"format": "other"}, {"cases_scored": 0}, {"aggregate": {}}, {"suit": ""}, {"evaluation_id": ""},
                                    {"aggregate": {"current": {"success_rate": 1}}}])
def test_bad_or_empty_results_do_not_mark_a_suit_evaluated(store, change):
    _suit(store)
    with pytest.raises(DarwinError):
        suits.import_evaluation(store, _payload(**change))
    assert suits.get_suit(store, "job")["status"] == "proposed"


def test_unknown_suit_is_refused(store):
    with pytest.raises(DarwinError) as e:
        suits.import_evaluation(store, _payload(slug="nope"))
    assert e.value.code == "not_found"


# ---------------------------------------------------------------------- through the app (REST + tools)

@pytest.fixture
def client(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", port=5233, data_dir_configured=True, hub_url="http://127.0.0.1:9", hoards_root=tmp_path / "hoards")
    d = tmp_path / "hoards" / "Faustusables" / "Ana's Hoard"
    d.mkdir(parents=True)
    (d / "faustus-plugin.json").write_text('{"id": "ana", "name": "Ana\'s Hoard", "capabilities": ["ocr"]}', encoding="utf-8")
    app = create_app(cfg, background=False)
    with TestClient(app, base_url="http://127.0.0.1:5233", client=("127.0.0.1", 50000)) as c:
        c.app.state.services.settings["faustus_url"] = "http://127.0.0.1:9"
        yield c


def test_rest_and_tools_end_to_end(client):
    listing = client.get("/api/suits").json()
    assert listing["total"] == 6 and listing["counts"]["proposed"] + listing["counts"]["partial"] == 6
    client.post("/api/tree/refresh")
    r = client.post("/api/capabilities/mark", json={"key": "cap:ana:ocr", "implemented": True, "evidence": []})
    assert r.status_code == 400
    ok = client.post("/api/capabilities/mark", json={"key": "cap:ana:ocr", "implemented": True,
                                                     "evidence": [{"kind": "test", "ref": "tests/test_ocr.py::test_reads"}]}).json()
    assert ok["implemented"] is True
    client.put("/api/suits/ocr-job", json={"name": "OCR job", "operations": [{"name": "ocr", "capability_key": "cap:ana:ocr"}]})
    assert client.get("/api/suits/ocr-job").json()["status"] == "backed"
    gap = client.post("/api/ui/call", json={"name": "darwin_gap_add", "arguments": {"title": "Hacer OCR de capturas", "target": "ana"}}).json()
    rec = client.post("/api/gaps/reconcile", json={}).json()
    assert [g["id"] for g in rec["possibly_stale"]] == [gap["id"]] and rec["open"] == 0
    gaps = client.get("/api/gaps").json()
    assert gaps["open"] == 0 and gaps["gaps"][0]["possibly_stale"]["evidence"][0]["kind"] == "test"
    assert client.get("/api/overview").json()["counts"]["gaps_open"] == 0
    imp = client.post("/api/evaluations", json=_payload(slug="ocr-job")).json()
    assert imp["suit"]["status"] == "evaluated"
    names = {t["name"] for t in client.get("/api/agent/tools", headers={"Authorization": f"Bearer {client.app.state.services.token}"}).json()["tools"]}
    assert {"darwin_suits", "darwin_suit_get", "darwin_suit_save", "darwin_gaps_reconcile", "darwin_capability_mark",
            "darwin_suit_import_eval", "darwin_suits_seed", "darwin_suit_delete"} <= names
    assert client.delete("/api/suits/ocr-job").json() == {"deleted": "ocr-job"}
