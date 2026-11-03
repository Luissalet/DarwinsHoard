from __future__ import annotations

import pytest

from darwin_hoard import query
from darwin_hoard.legacy import LegacyImporter, app_mentions, parse_radar_line
from darwin_hoard.store import Store

RADAR = """# Radar

1. **[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)** · ⭐ 229.2k — Harness donde todo es plugin.
96. **[redhat-et/ripwire](https://github.com/redhat-et/ripwire)** · ⭐ 1.2k — Qué se rompe y qué tests corro.
382. **Claude Ads** 📌 · fuente: https://github.com/AgriciDaniel/claude-ads · fuera de tema (el método sí) — **Cómo en Vitruvius y auditorías:** nota determinista.
534. **[earshot/earshot](https://github.com/earshot/earshot)** · ⭐ ~900 · NEW (MIT) — escucha audio. **Cómo:** sonido en Prospero y Vitruvius (#1674).
546. **Voxel suite** (Roblox) · SKIP — no encontrado.
"""

IDEAS = """# Radar 426-510
- **#503** **[graygnatconsole/mcp-audit-tool](https://github.com/graygnatconsole/mcp-audit-tool)** · — · H/G · NEW — auditoría MCP. Destino: Faustus. Hecho el 11-10.
- **#510** **[hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)** · ⭐ ~28k · M · COVERED — presentaciones. Cicero ya exporta.
"""

TRACKER = """| # | Repo | Estado | Qué se hizo / por qué no | Commit |
|---|---|---|---|---|
| 096 | redhat-et/ripwire | ✅ | Sin compilar su binario: su idea sobre el grafo propio. | 50e62de8, afe4038e |
| 001 | deepseek-ai/deepseek-harness | ➖ cubierto | Ya lo cubren los plugins. | — |
| 047 | mksglu/context-mode | ⏸ | Falta medir. | cf80f044 |
"""

GUIDE = """- [x] **096** [redhat-et/ripwire](https://github.com/redhat-et/ripwire) · mejora · Impacto de cambios · [guía](g/096.md)
- [~] **001** [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) · mejora · Todo es plugin · [guía](g/001.md)
"""


@pytest.fixture
def env(tmp_path):
    insp = tmp_path / "insp"
    insp.mkdir()
    (insp / "RADAR_GITTREND.md").write_text(RADAR, encoding="utf-8")
    (insp / "IMPLEMENTACION_RADAR.md").write_text(TRACKER, encoding="utf-8")
    (insp / "GUIA_IMPLEMENTACION.md").write_text(GUIDE, encoding="utf-8")
    ideas = tmp_path / "radar-ideas.md"
    ideas.write_text(IDEAS, encoding="utf-8")
    store = Store(tmp_path / "d.db")
    yield store, insp, ideas
    store.close()


def test_parse_radar_formats():
    e = parse_radar_line("382. **Claude Ads** 📌 · fuente: https://github.com/AgriciDaniel/claude-ads · fuera de tema — **Cómo en Vitruvius:** x",
                         10, 382)
    assert e.repo == "AgriciDaniel/claude-ads" and e.title == "Claude Ads" and e.pinned and e.label == "off-topic"
    assert e.targets == ["vitruvius"]
    e2 = parse_radar_line("- **#503** **[g/mcp-audit-tool](https://github.com/g/mcp-audit-tool)** · — · H/G · NEW — x. Destino: Faustus.", 3, 503)
    assert e2.repo == "g/mcp-audit-tool" and e2.label == "new" and e2.targets == ["faustus"]
    assert app_mentions("en Prospero's Hoard y Hoard Link") == ["prospero", "hoardhub"]


def test_import_all_is_idempotent_and_keeps_provenance(env):
    store, insp, ideas = env
    imp = LegacyImporter(store)
    first = imp.import_all(inspiration_dir=insp, radar_ideas=ideas, agora=False)
    counts1 = store.counts()
    second = imp.import_all(inspiration_dir=insp, radar_ideas=ideas, agora=False)
    assert store.counts() == counts1
    assert second["radar"]["new_captures"] == 0 and first["radar"]["new_captures"] == 5
    # radar 96, tracker 096 and guide 096 are the same source with three appearances
    g = query.genealogy(store, radar_no=96)
    assert {c["channel"] for c in g["captures"]} == {"radar", "tracker", "guide"}
    cap = next(c for c in g["captures"] if c["channel"] == "tracker")
    assert cap["provenance"]["line"] == 3 and len(cap["provenance"]["file_sha256"]) == 64
    # tracker ✅ with two commits: two declared deliveries, verification only documented
    assert {d["commit_sha"] for d in g["deliveries"]} == {"50e62de8", "afe4038e"}
    assert all(d["implementation"] == "integrada" and d["verification"] == "documentada" for d in g["deliveries"])
    assert g["state"] == "integrada"


def test_states_map_without_inventing(env):
    store, insp, ideas = env
    LegacyImporter(store).import_all(inspiration_dir=insp, radar_ideas=ideas, agora=False)
    covered = query.genealogy(store, radar_no=1)
    assert {p["state"] for p in covered["proposals"] if p["target"] == "faustus"} == {"cubierta"}
    paused = query.genealogy(store, radar_no=47)
    assert paused["deliveries"][0]["implementation"] == "parcial"
    earshot = query.genealogy(store, radar_no=534)
    assert {p["target"] for p in earshot["proposals"]} == {"prospero", "vitruvius"}
    skip = query.genealogy(store, radar_no=546)
    assert skip["source"]["kind"] == "idea" and skip["proposals"][0]["state"] == "descartada"
    assert query.genealogy(store, radar_no=510)["proposals"][0]["state"] == "cubierta"


def test_find_filters(env):
    store, insp, ideas = env
    LegacyImporter(store).import_all(inspiration_dir=insp, radar_ideas=ideas, agora=False)
    assert query.find(store, query="#96")["items"][0]["repo"] == "redhat-et/ripwire"
    assert query.find(store, query="https://github.com/redhat-et/ripwire/tree/main")["total"] == 1
    assert {i["radar_no"] for i in query.find(store, target="prospero")["items"]} == {534}
    assert {i["radar_no"] for i in query.find(store, state="integrada")["items"]} == {96}
    assert {i["radar_no"] for i in query.find(store, channel="radar-ideas")["items"]} == {503, 510}
    assert query.find(store, pinned=True)["items"][0]["radar_no"] == 382
    ordered = [i["radar_no"] for i in query.find(store, order="radar")["items"]]
    assert ordered == sorted(ordered)


def test_two_radar_entries_on_one_source_both_count(tmp_path):
    insp = tmp_path / "i"
    insp.mkdir()
    (insp / "RADAR_GITTREND.md").write_text(
        "1. **[llama.cpp v0.6.0](https://github.com/ggml-org/llama.cpp/releases)** · D · PARTIAL — a\n"
        "2. **[llama.cpp b11435](https://github.com/ggml-org/llama.cpp/releases)** · D · COVERED — b\n", encoding="utf-8")
    store = Store(tmp_path / "d.db")
    rep = LegacyImporter(store).import_all(inspiration_dir=insp, agora=False)
    assert store.counts()["sources"] == 1 and store.counts()["captures"] == 2
    assert rep["radar_numbers"]["missing"] == [] and rep["radar_numbers"]["distinct"] == 2
    assert query.find(store, query="#2")["total"] == 1
    store.close()


def test_aggregate_mixed_and_proof(tmp_path):
    import subprocess
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="a/b")
    store.upsert_proposal(key="a->x", source_id=sid, target="x", state="aceptada", origin="agora")
    store.upsert_proposal(key="a->y", source_id=sid, target="y", state="aceptada", origin="agora")
    repo = tmp_path / "r"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (repo / "f").write_text("1")
    git("add", "f")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    sha = git("rev-parse", "HEAD")
    store.upsert_delivery(key="d1", source_id=sid, target="x", repo="R", commit_sha=sha[:8], implementation="integrada", verification="documentada")
    g = query.genealogy(store, source_id=sid)
    assert g["state"] == "mixta" and g["proof"] == "documentos"
    from darwin_ingest import verify_deliveries
    verify_deliveries(store, {"R": str(repo)})
    g = query.genealogy(store, source_id=sid)
    assert g["proof"] == "en_main"
    store.upsert_proposal(key="a->y", source_id=sid, target="y", state="descartada", origin="luis")
    assert query.genealogy(store, source_id=sid)["state"] == "integrada"
    store.close()


def test_inbox_keeps_captures_without_source(tmp_path):
    store = Store(tmp_path / "d.db")
    from darwin_ingest import ingest_batch
    ingest_batch(store, [{"capture_key": "w:1", "text": "mira esto luego"}, {"capture_key": "w:2", "text": "https://github.com/a/b"}], channel="whatsapp")
    box = query.inbox(store)
    assert box["total"] == 1 and box["items"][0]["text"] == "mira esto luego"
    assert query.find(store, channel="whatsapp")["total"] == 1
    store.close()


def test_aggregate_is_per_capability_not_per_target(tmp_path):
    """Two proposals for two capabilities of the same app: one integrated delivery for one of them is «mixta», not «integrada»."""
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="c/d")
    pa = store.upsert_proposal(key="c->faustus#a", source_id=sid, target="faustus", capability_key="cap:a", state="aceptada", origin="agora")
    pb = store.upsert_proposal(key="c->faustus#b", source_id=sid, target="faustus", capability_key="cap:b", state="pendiente", origin="agora")
    store.upsert_delivery(key="da", source_id=sid, target="faustus", capability_key="cap:a", commit_sha="abc1234",
                          implementation="integrada", verification="documentada")
    assert query.genealogy(store, source_id=sid)["state"] == "mixta"
    assert query.find(store, query="c/d")["items"][0]["state"] == "mixta"
    assert query.overview(store)["sources_by_state"].get("mixta") == 1
    # b only partial: still not everything is done
    store.upsert_delivery(key="db", source_id=sid, target="faustus", capability_key="cap:b", implementation="parcial")
    assert query.genealogy(store, source_id=sid)["state"] == "mixta"
    # b integrated too: now the whole source is
    did = store.one("SELECT id FROM deliveries WHERE key='db'")["id"]
    store.set_state("deliveries", did, "implementation", "integrada")
    assert query.genealogy(store, source_id=sid)["state"] == "integrada"
    assert pa != pb
    store.close()


def test_aggregate_matches_deliveries_by_proposal_and_never_closes_two_capabilities_with_one_unnamed_delivery(tmp_path):
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="e/f")
    pa = store.upsert_proposal(key="e->x#a", source_id=sid, target="x", capability_key="cap:a", state="aceptada", origin="agora")
    store.upsert_proposal(key="e->x#b", source_id=sid, target="x", capability_key="cap:b", state="aceptada", origin="agora")
    # a delivery for the app that names neither proposal nor capability cannot say which of the two it closed
    store.upsert_delivery(key="dx", source_id=sid, target="x", commit_sha="1234567", implementation="integrada")
    assert query.genealogy(store, source_id=sid)["state"] == "mixta"
    # linked to proposal a: still only a
    store.upsert_delivery(key="dx2", source_id=sid, target="x", proposal_id=pa, commit_sha="2345678", implementation="integrada")
    assert query.genealogy(store, source_id=sid)["state"] == "mixta"
    # once b is discarded, every open unit is done
    pb = store.one("SELECT id FROM proposals WHERE key='e->x#b'")["id"]
    store.set_state("proposals", pb, "state", "descartada")
    assert query.genealogy(store, source_id=sid)["state"] == "integrada"
    store.close()


def test_aggregate_single_proposal_per_app_keeps_target_level_matching(tmp_path):
    """The usual case (one proposal per app, deliveries that name only the app) is unchanged."""
    store = Store(tmp_path / "d.db")
    sid = store.upsert_source(repo="g/h")
    store.upsert_proposal(key="g->x", source_id=sid, target="x", capability_key="cap:a", state="aceptada", origin="agora")
    store.upsert_delivery(key="dg", source_id=sid, target="x", implementation="parcial")
    assert query.genealogy(store, source_id=sid)["state"] == "parcial"
    store.upsert_delivery(key="dg2", source_id=sid, target="x", commit_sha="3456789", implementation="integrada")
    assert query.genealogy(store, source_id=sid)["state"] == "integrada"
    store.close()
