"""Coverage against the tree, the gap-driven radar, saved questions, proposals list, saved filters and the panel."""
import time

from darwin_hoard import coverage, radar, views, watches
from darwin_hoard.store import Store


def _cap(store, key, parent, level, name, app, detail="", evidence="declarada"):
    with store.tx() as c:
        c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail, evidence, operation, since, seen) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (key, parent, level, name, app, detail, evidence, "disponible", 0, 0))


def _seed(tmp_path):
    store = Store(tmp_path / "d.db")
    _cap(store, "faustus", None, "root", "Faustus", "faustus")
    _cap(store, "app:talos", "faustus", "app", "Talos's Hoard", "talos")
    _cap(store, "cap:talos:ocr", "app:talos", "capability", "ocr screenshot text extraction", "talos", evidence="viva")
    _cap(store, "tool:talos:read", "app:talos", "tool", "talos_read_screenshot", "talos", "Read screenshot text with OCR", "viva")
    _cap(store, "app:silver", "faustus", "app", "Silver's Hoard", "silver")
    _cap(store, "cap:silver:battle", "app:silver", "capability", "pokemon battle simulator", "silver")
    return store


def test_coverage_verdicts(tmp_path):
    store = _seed(tmp_path)
    cov = coverage.classify(store, text="Read text from screenshot images with OCR extraction")
    assert cov["verdict"] == "covered" and cov["apps"][0]["app_id"] == "talos"
    assert any(n["key"] == "cap:talos:ocr" for n in cov["apps"][0]["nodes"])
    part = coverage.classify(store, text="pokemon team builder with damage calculator and battle replays")
    assert part["verdict"] == "partial" and part["apps"][0]["app_id"] == "silver"
    gap = coverage.classify(store, text="knitting pattern generator for sweaters")
    assert gap["verdict"] == "gap" and not gap["apps"]
    sid = store.upsert_source(repo="a/screenshot-ocr", title="screenshot-ocr", summary="OCR text extraction from screenshots")
    assert coverage.classify(store, source_id=sid)["verdict"] == "covered"


def test_radar_plan_ranks_and_stays_quiet_without_news(tmp_path):
    store = _seed(tmp_path)
    old = store.add_gap(title="Generar patrones de punto para jerséis", detail="knitting patterns")
    covered = store.add_gap(title="Read text from screenshot images with OCR extraction")
    p1 = radar.plan(store, now=time.time())
    ids = [g["gap_id"] for g in p1["gaps"]]
    assert ids.index(old) < ids.index(covered)
    assert next(g for g in p1["gaps"] if g["gap_id"] == covered)["coverage"] == "covered"
    assert p1["gaps"][0]["queries"]["github"].endswith("in:name,description,readme")
    assert p1["notify"] is True
    p2 = radar.plan(store)
    assert p2["notify"] is False and "Sin novedades" in p2["summary"]
    sid = store.upsert_source(repo="b/knit", title="knitting patterns generator for jerseis")
    p3 = radar.plan(store)
    assert p3["notify"] is True and sid in p3["novelty"]["new_candidates"]


def test_radar_run_reports_known_and_registers_new(tmp_path):
    store = _seed(tmp_path)
    gid = store.add_gap(title="knitting pattern generator", detail="sweater knitting patterns")
    known = store.upsert_source(repo="x/known-knit", title="known")
    calls = []

    def search(q, n):
        calls.append(q)
        return [{"full_name": "x/known-knit", "url": "https://github.com/x/known-knit", "description": "", "stars": 3, "license": "MIT"},
                {"full_name": "y/new-knit", "url": "https://github.com/y/new-knit", "description": "knitting", "stars": 9, "license": ""}]

    out = radar.run(store, top=1, add=True, search=search)
    assert calls and out["new"] == 1 and out["added"] == 1
    repos = {r["full_name"]: r for r in out["results"][0]["repos"]}
    assert repos["x/known-knit"]["known"] and repos["x/known-knit"]["source_id"] == known
    new_id = repos["y/new-knit"]["source_id"]
    assert store.one("SELECT channel FROM captures c JOIN capture_sources cs ON cs.capture_id=c.id WHERE cs.source_id=?", (new_id,))["channel"] == "radar"
    assert str(gid) in store.get_meta("radar_searched")
    again = radar.run(store, top=1, add=True, search=search)
    assert again["new"] == 0 and again["notify"] is False

    def broken(q, n):
        raise OSError("rate limited")
    assert radar.run(store, gap_ids=[gid], search=broken)["errors"][0]["gap_id"] == gid


def test_saved_question_baseline_then_news(tmp_path):
    store = _seed(tmp_path)
    store.upsert_source(repo="a/meeting-notes", title="meeting transcription notes")
    w = watches.add(store, "¿qué hay para transcribir reuniones?")
    assert w["seen"]["discoveries"] and not w.get("last_news")
    assert watches.check_all(store)["notify"] is False
    sid = store.upsert_source(repo="b/whisper-meetings", title="meeting transcription with whisper")
    res = watches.check_all(store)
    assert res["notify"] is True and res["with_news"][0]["news"]["discoveries"][0]["id"] == sid
    assert watches.listing(store)["with_news"] == 1
    watches.set_state(store, w["id"], clear_news=True, state="pausada")
    assert watches.check_all(store)["checked"] == 0
    assert watches.set_state(store, w["id"], delete=True) == {"deleted": w["id"]}


def test_proposals_filters_and_panel(tmp_path):
    store = _seed(tmp_path)
    s1 = store.upsert_source(repo="a/ocr-tool", title="ocr tool")
    s2 = store.upsert_source(repo="b/battle", title="battle ai")
    store.upsert_proposal(key="p1", source_id=s1, target="talos", state="pendiente", origin="agent", reason="better OCR")
    store.upsert_proposal(key="p2", source_id=s2, target="silver", state="aceptada", origin="luis")
    lst = views.proposals(store, target="talos")
    assert lst["total"] == 1 and lst["items"][0]["title"] == "ocr tool" and lst["counts"]["pendiente"] == 1
    assert views.proposals(store, query_text="battle")["items"][0]["target"] == "silver"
    views.save_filter(store, "Talos abiertos", {"target": "talos", "order": "fitness", "junk": 1})
    args = views.apply_filter(store, "Talos abiertos", {"query": "", "target": "", "order": "recent"})
    assert args["target"] == "talos" and args["order"] == "fitness" and "junk" not in views.saved_filters(store)["Talos abiertos"]
    assert "Talos abiertos" not in views.delete_filter(store, "Talos abiertos")["filters"]
    assert views.resolve_app(store, project="Talos's Hoard")["app_id"] == "talos"
    assert views.resolve_app(store, space="silver")["app_id"] == "silver"
    assert views.resolve_app(store, space="research") is None
    p = views.panel(store, project="Silver's Hoard")
    assert p["scope"] == "app" and p["proposals_by_state"] == {"aceptada": 1}
    fam = views.panel(store, space="research")
    assert fam["scope"] == "family" and "radar" in fam and not fam["unresolved"]
    assert views.panel(store, project="Nada que ver")["unresolved"] is True


def test_tools_reach_the_new_views(tmp_path):
    from fastapi.testclient import TestClient
    from darwin_hoard.config import Config
    from darwin_hoard.main import create_app
    cfg = Config(data_dir=tmp_path / "data", port=5233, data_dir_configured=True, hub_url="http://127.0.0.1:9", hoards_root=tmp_path / "h")
    with TestClient(create_app(cfg, background=False), base_url="http://127.0.0.1:5233", client=("127.0.0.1", 50000)) as c:
        c.app.state.services._translate = lambda gaps: {g["id"]: "knitting pattern generator" for g in gaps}  # no model in tests
        c.post("/api/ui/call", json={"name": "darwin_gap_add", "arguments": {"title": "knitting pattern generator"}})
        plan = c.get("/api/radar/plan").json()
        assert plan["open_gaps"] == 1 and plan["gaps"][0]["queries"]["github"].startswith("knitting pattern generator")
        assert plan["gaps"][0]["queries"]["source"] == "model"
        w = c.post("/api/watches", json={"question": "patrones de punto"}).json()
        assert c.get("/api/watches").json()["active"] == 1
        assert c.post("/api/watches/check").json()["checked"] == 1
        assert c.delete(f"/api/watches/{w['id']}").json() == {"deleted": w["id"]}
        assert c.put("/api/filters/Mios", json={"pinned": True}).json()["filters"]["Mios"]["pinned"] is True
        assert c.get("/api/discoveries", params={"q": ""}).status_code == 200
        r = c.post("/api/ui/call", json={"name": "darwin_find", "arguments": {"saved": "Mios"}})
        assert r.status_code == 200 and r.json()["total"] == 0
        assert c.post("/api/ui/call", json={"name": "darwin_find", "arguments": {"saved": "nope"}}).status_code == 404
        assert c.get("/api/coverage", params={"text": "knitting sweater patterns"}).json()["verdict"] in ("gap", "unknown")
        assert c.get("/api/proposals").json()["total"] == 0
        assert c.get("/api/panel", params={"space": "research"}).json()["scope"] == "family"


def test_model_keywords_are_cached_per_gap_text(tmp_path):
    store = _seed(tmp_path)
    gid = store.add_gap(title="Atajo global para captura de pantalla")
    calls = []

    def translate(gaps):
        calls.append([g["id"] for g in gaps])
        return {g["id"]: "global hotkey screen capture" for g in gaps}

    p = radar.plan(store, translate=translate)
    assert p["gaps"][0]["queries"]["github"] == "global hotkey screen capture in:name,description,readme"
    radar.plan(store, translate=translate)
    assert calls == [[gid]]
    with store.tx() as c:
        c.execute("UPDATE gaps SET detail='también vídeo' WHERE id=?", (gid,))
    radar.plan(store, translate=translate)
    assert calls == [[gid], [gid]]
    assert radar.plan(store, translate=lambda g: (_ for _ in ()).throw(RuntimeError("no model")))["gaps"][0]["queries"]["source"] == "model"


def test_link_collections_are_not_candidates():
    assert radar.is_collection({"full_name": "jaywcjlove/awesome-mac", "description": "Now we have become very big"})
    assert radar.is_collection({"name": "Best-websites", "description": "A list of best websites a programmer should visit"})
    assert radar.is_collection({"name": "x", "topics": ["awesome-list"]})
    assert not radar.is_collection({"full_name": "nicehash/hotkeys", "description": "Global hotkeys for screen capture"})
