"""The MCP bridge never starts Darwin (Hoards are used on demand): connecting, listing and calling leave a stopped app stopped."""

from __future__ import annotations

import asyncio

import mcp_server
from darwin_hoard.hoard_link import bridge as hl_bridge


def test_bridge_never_starts_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_URL", "http://127.0.0.1:9")          # nothing listens there
    monkeypatch.setenv("DARWIN_BRIDGE_AUTOSTART", "1")              # even an old opt-in variable does not turn it on
    monkeypatch.setenv("DARWIN_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DARWIN_TOKEN_FILE", raising=False)
    monkeypatch.delenv("DARWIN_TOKEN", raising=False)
    (tmp_path / "mcp-token").write_text("t" * 32, encoding="utf-8")
    started: list = []
    monkeypatch.setattr(hl_bridge, "ensure_running", lambda *a, **k: started.append((a, k)) or True)

    b = mcp_server.build_bridge()
    assert b.autostart is False and b.autostart_enabled() is False

    async def run():
        await b._prefetch()                                         # what run_bridge does when the MCP client connects
        listed = await b.list_tools()
        result = await b.call("darwin_find", {"query": "ocr"})
        return listed, result

    listed, result = asyncio.run(run())
    names = {t["name"] for t in listed}
    assert {"darwin_find", "darwin_capability_find", "darwin_tree"} <= names   # cold catalogue from the package
    assert result.is_error and result.body["code"] == "not_running"
    assert "Hoard Hub" in result.body["error"]
    assert started == []


def test_bridge_start_app_is_a_no_op_when_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DARWIN_DATA_DIR", str(tmp_path))
    started: list = []
    monkeypatch.setattr(hl_bridge, "ensure_running", lambda *a, **k: started.append(a) or True)
    assert mcp_server.build_bridge().start_app(wait_s=0.1) is False
    assert started == []
