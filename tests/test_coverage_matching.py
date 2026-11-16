"""darwin_coverage must not call something covered because words of a description (or furniture words every app has) overlap."""
from darwin_hoard import coverage
from darwin_hoard.store import Store


def _cap(store, key, parent, level, name, app, detail="", evidence="viva"):
    with store.tx() as c:
        c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail, evidence, operation, since, seen) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (key, parent, level, name, app, detail, evidence, "disponible", 0, 0))


def _family(tmp_path):
    """A tree where «code» and «thread» name nodes in many apps, plus the two nodes that used to match by their descriptions."""
    store = Store(tmp_path / "d.db")
    _cap(store, "faustus", None, "root", "Faustus", "faustus")
    for i, app in enumerate(("writer", "silver", "talos", "kafka", "links", "atlas", "hermes")):
        _cap(store, f"app:{app}", "faustus", "app", app, app)
        _cap(store, f"tool:{app}:code{i}", f"app:{app}", "tool", f"{app}_code_check", app, "checks code", "viva")
        _cap(store, f"tool:{app}:thread{i}", f"app:{app}", "tool", f"{app}_thread_note", app, "a thread of notes", "viva")
    _cap(store, "app:blender", "faustus", "app", "blender", "blender")
    _cap(store, "tool:blender:submit", "app:blender", "tool", "blender_live_submit", "blender",
         "Submit Python code to run inside a live Blender session, on its own thread, with the agents control of the scene", "viva")
    _cap(store, "app:floorplan", "faustus", "app", "code_floorplan", "floorplan")
    _cap(store, "tool:floorplan:map", "app:floorplan", "tool", "code_floorplan_map", "floorplan",
         "Read a repository, its plugins and official docs, and draw the floorplan of its code", "viva")
    _cap(store, "app:hub", "faustus", "app", "hoardhub", "hoardhub")
    _cap(store, "cap:hub:agents", "app:hub", "capability", "coding agents sessions", "hoardhub", "agent sessions", "viva")
    _cap(store, "cap:hub:control", "app:hub", "capability", "agents control panel", "hoardhub", "", "viva")
    return store


def test_t3code_is_not_covered_by_a_blender_tool(tmp_path):
    store = _family(tmp_path)
    sid = store.upsert_source(repo="pingdotgg/t3code", title="pingdotgg/t3code",
                              summary="Minimal web GUI for coding agents: code, control the agents, one thread per task")
    got = coverage.classify(store, source_id=sid)
    apps = {a["app_id"]: a for a in got["apps"]}
    assert "blender" not in apps, apps.get("blender")
    assert got["verdict"] in ("covered", "partial") and got["apps"][0]["app_id"] == "hoardhub"
    assert "code" in got["common_terms"] and "thread" in got["common_terms"]


def test_hermes_plugins_are_not_covered_by_a_floorplan_tool(tmp_path):
    store = _family(tmp_path)
    sid = store.upsert_source(repo="NousResearch/hermes-official-plugins", title="NousResearch/hermes-official-plugins",
                              summary="Official plugins catalogue for the Hermes agent, with the code of every plugin")
    got = coverage.classify(store, source_id=sid)
    assert "floorplan" not in {a["app_id"] for a in got["apps"]}
    assert got["verdict"] != "covered"


def test_a_word_every_app_has_does_not_make_a_match(tmp_path):
    store = _family(tmp_path)
    got = coverage.classify(store, text="code thread code thread helper utilities")
    assert got["verdict"] in ("gap", "unknown") and "code" in got["common_terms"]
