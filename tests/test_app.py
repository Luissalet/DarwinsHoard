from __future__ import annotations

from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from darwin_hoard.config import Config
from darwin_hoard.main import create_app


@pytest.fixture
def client(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", port=5233, data_dir_configured=True, hub_url="http://127.0.0.1:9", hoards_root=tmp_path / "hoards")
    manifest_dir = cfg.hoards_root / "Faustusables" / "Screenshot Reader"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "faustus-plugin.json").write_text(
        '{"id": "screenshot-reader", "name": "Screenshot Reader", "purpose": "Reads screenshots with OCR.", '
        '"capabilities": ["ocr", "screen-history"]}',
        encoding="utf-8")
    (cfg.hoards_root / "Faustusnt" / "Standalone Utility").mkdir(parents=True)
    app = create_app(cfg, background=False)
    with TestClient(app, base_url="http://127.0.0.1:5233", client=("127.0.0.1", 50000)) as c:
        c.app.state.services.settings["faustus_url"] = "http://127.0.0.1:9"
        yield c


@pytest.fixture
def offline_tree_sources(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise URLError("tree source is offline")

    # Covers placement discovery as well as both sources of tree data.
    monkeypatch.setattr("urllib.request.urlopen", unavailable)


def test_health_and_add_then_existing(client):
    h = client.get("/api/health").json()
    assert h["service"] == "darwins-hoard"
    r = client.post("/api/ui/call", json={"name": "darwin_add", "arguments": {"text": "mira https://github.com/A/B?tab=x", "target": "links"}}).json()
    assert r["sources"][0]["existing"] is False and r["sources"][0]["source"]["repo"] == "A/B"
    r2 = client.post("/api/ui/call", json={"name": "darwin_add", "arguments": {"text": "github.com/a/b"}}).json()
    assert r2["sources"][0]["existing"] is True
    assert r2["sources"][0]["proposals"][0]["target"] == "links"
    lst = client.get("/api/discoveries", params={"q": "a/b"}).json()
    assert lst["total"] == 1



def test_owner_attribution_preserves_old_decisions_and_distinguishes_agent(client):
    svc = client.app.state.services
    store = svc.store
    source_id = store.upsert_source(url="https://example.test/legacy")
    proposal_id = store.upsert_proposal(key="legacy", source_id=source_id, target="links", origin="agent")
    store.set_state("proposals", proposal_id, "state", "aceptada", by="previous-profile", note="Stored decision")
    store.add_capture(capture_key="legacy-capture", channel="manual", text="Previous capture", author="previous-profile",
                      provenance={"via": "darwin_add"}, source_id=source_id)
    client.put("/api/settings", json={"owner_name": "Review profile", "whatsapp_account": "separate-chat-account"}).raise_for_status()

    args = {"entity": "proposals", "id": proposal_id, "field": "state", "value": "descartada", "by": "Review profile"}
    headers = {"Authorization": f"Bearer {svc.token}"}
    def set_state(route, arguments, **kwargs):
        return client.post(route, json={"name": "darwin_set_state", "arguments": arguments}, **kwargs).raise_for_status().json()

    assert set_state("/api/agent/call", args, headers=headers)["changed"] is False
    updated = set_state("/api/ui/call", args)
    assert updated["changed"]
    assert [row["by"] for row in updated["history"]] == ["previous-profile", "Review profile"]
    assert updated["history"][0]["note"] == "Stored decision"
    [owned] = client.get("/api/proposals", params={"origin": "owner"}).json()["items"]
    assert owned["origin_actor"] == "Review profile"

    added = client.post("/api/agent/call", headers=headers, json={
        "name": "darwin_add", "arguments": {"text": "https://example.test/agent", "target": "links",
                                            "channel": "manual", "author": "Review profile"}
    }).raise_for_status().json()
    capture = store.one("SELECT author, provenance FROM captures WHERE id=?", (added["capture_id"],))
    assert capture["author"] == "agent"
    assert capture["provenance"]["actor_role"] == "agent"



def test_legacy_reply_filter_and_origin_work_without_saved_settings(tmp_path):
    from darwin_hoard.store import Store
    from darwin_ingest import ingest_batch

    former_owner = "previous_profile"
    alternate_filter = "from_unconfigured_profile"
    cfg = Config(data_dir=tmp_path / "data", port=5233, data_dir_configured=True, hub_url="http://127.0.0.1:9")
    old = Store(cfg.db_path)
    url = "https://example.test/old"
    source = old.upsert_source(url=url)
    proposal = old.upsert_proposal(key="old:decision", source_id=source, target="links", origin=former_owner)
    old.set_state("proposals", proposal, "state", "aceptada", by=former_owner, note="Historical choice")
    old.upsert_proposal(key="old:links", source_id=source, target="tracker", origin="links")
    quoted = {"id": "quoted", "text": url}
    ingest_batch(old, [
        {"capture_key": "own", "text": "Own saved reply", "provenance": {"from_me": True}, "reply_to": quoted},
        {"capture_key": "other", "text": "Other saved reply", "provenance": {"from_me": False}, "reply_to": quoted},
    ], channel="whatsapp")
    old.close()

    with TestClient(create_app(cfg, background=False), base_url="http://127.0.0.1:5233", client=("127.0.0.1", 50000)) as client:
        svc = client.app.state.services
        headers = {"Authorization": f"Bearer {svc.token}"}
        reply_filter = client.post("/api/agent/call", headers=headers, json={
            "name": "darwin_comments", "arguments": {alternate_filter: False},
        }).raise_for_status().json()
        assert reply_filter["total"] == 2
        assert {item[alternate_filter] for item in reply_filter["items"]} == {False, True}
        old_query = client.get("/api/comments", params={f"from_{former_owner}": "false"}).raise_for_status().json()
        assert old_query["total"] == 2
        both = client.get("/api/comments", params={f"from_{former_owner}": "false", "from_me": "true"}).raise_for_status().json()
        assert both["total"] == 1

        for origin in ("owner", former_owner):
            [owner_row] = client.get("/api/proposals", params={"origin": origin}).json()["items"]
            assert owner_row["id"] == proposal and owner_row["origin"] == former_owner
            assert owner_row["origin_role"] == "owner" and owner_row["state"] == "aceptada"
        replay = client.post("/api/agent/call", headers=headers, json={
            "name": "darwin_set_state", "arguments": {"entity": "proposals", "id": proposal, "field": "state", "value": "descartada"},
        }).raise_for_status().json()
        assert replay["changed"] is False
        assert replay["history"][0]["note"] == "Historical choice"


@pytest.mark.usefixtures("offline_tree_sources")
def test_tree_from_manifests_when_hub_down(client):
    rep = client.post("/api/tree/refresh").json()
    assert rep["hub"]["ok"] is False
    assert rep["faustus"]["ok"] is False
    assert rep["manifests"] == {"ok": True, "manifests": 1}
    t = client.get("/api/tree", params={"root": "hoardhub", "depth": 2}).json()["tree"]
    names = {c["name"] for c in t["children"]}
    assert {"Screenshot Reader", "Standalone Utility"} <= names
    found = client.get("/api/capabilities/find", params={"q": "dónde hacemos ocr"}).json()
    [app] = found["apps"]
    assert app["app_id"] == "screenshot-reader"
    assert any(match["name"] == "ocr" and match["evidence"] == "declarada" for match in app["matches"])
    assert app["path"][:2] == ["Faustus", "Hoard Hub"]


def test_set_state_requires_evidence_for_integrated(client):
    client.post("/api/ui/call", json={"name": "darwin_add", "arguments": {"text": "x/y", "target": "faustus"}})
    s = client.get("/api/discoveries", params={"q": "x/y"}).json()["items"][0]
    store = client.app.state.services.store
    did = store.upsert_delivery(key="k", source_id=s["id"], target="faustus")
    bad = client.post("/api/ui/call", json={"name": "darwin_set_state", "arguments": {"entity": "deliveries", "id": did,
                                                                                       "field": "implementation", "value": "integrada"}})
    assert bad.status_code == 400
    ok = client.post("/api/ui/call", json={"name": "darwin_set_state", "arguments": {"entity": "deliveries", "id": did,
                                                                                      "field": "implementation", "value": "parcial"}}).json()
    assert ok["changed"] and ok["history"][0]["new"] == "parcial"


def test_agent_bridge_requires_token(client):
    denied = client.post("/api/agent/call", json={"name": "darwin_overview", "arguments": {}})
    assert denied.status_code in (401, 403)
    token = client.app.state.services.token
    tools = client.get("/api/agent/tools", headers={"Authorization": f"Bearer {token}"}).json()
    names = {t["name"] for t in tools["tools"]}
    assert {"darwin_add", "darwin_tree", "darwin_find", "darwin_source"} <= names
    ok = client.post("/api/agent/call", json={"name": "darwin_overview", "arguments": {}},
                     headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


@pytest.mark.usefixtures("offline_tree_sources")
def test_capability_find_ignores_stopwords(client):
    client.post("/api/tree/refresh")
    found = client.get("/api/capabilities/find", params={"q": "¿quién hace OCR?"}).json()
    assert found["terms"] == ["ocr"]


def test_repo_alias_rest_and_tool(client, tmp_path):
    r = client.get("/api/repo-aliases").json()
    assert any(a["name"] == "Galton's Hoard" and a["subdir"] == "galton_hoard" and a["origin"] == "builtin" for a in r["aliases"])
    folder = tmp_path / "old-repo"
    (folder / ".git").mkdir(parents=True)
    r = client.post("/api/repo-aliases", json={"name": "Some Old Hoard", "path": str(folder), "subdir": "pkg/"}).json()
    row = next(a for a in r["aliases"] if a["name"] == "Some Old Hoard")
    assert row["origin"] == "settings" and row["subdir"] == "pkg" and row["resolved_path"] == str(folder)
    assert client.get("/api/settings").json()["repo_aliases"]["Some Old Hoard"]["path"] == str(folder)
    r = client.post("/api/ui/call", json={"name": "darwin_repo_alias_set", "arguments": {"name": "Some Old Hoard", "remove": True}}).json()
    assert all(a["name"] != "Some Old Hoard" for a in r["aliases"])
    assert client.post("/api/repo-aliases", json={"name": "X"}).status_code == 400
