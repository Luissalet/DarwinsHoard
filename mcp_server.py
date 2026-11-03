"""Stdio MCP bridge for Darwin's Hoard.

It never opens the database itself: every tool call is proxied to the running app (`POST /api/agent/call`) with the
Bearer token from `<DATA_DIR>/mcp-token`; the tool list comes from `GET /api/agent/tools`.

Hoards are used on demand: connecting the MCP server, listing its tools or calling one never starts Darwin. While the
app is stopped the bridge lists the tools from the package's own catalogue (cold catalogue) and a call answers
`not_running` with how to start it. Start Darwin explicitly from the Hoard Hub (Start / Restart on its card, or
`POST <hub>/api/apps/darwin/start`), with `Iniciar Darwin's Hoard.cmd`, or with `python -m darwin_hoard`."""

from __future__ import annotations

import sys
import time
from typing import Any

from darwin_hoard.hoard_link.bridge import NOT_RUNNING, CatalogBridge


class DarwinBridge(CatalogBridge):
    """The family bridge with autostart off and a cold catalogue while the app is not running."""

    def cold_catalog(self) -> list[dict[str, Any]]:
        from darwin_hoard.agent_tools import AGENT_INSTRUCTIONS, tool_catalog
        if not self.instructions:
            self.instructions = AGENT_INSTRUCTIONS
        return [t for t in tool_catalog() if isinstance(t, dict) and t.get("name")]

    async def tools(self, *, force: bool = False) -> list[dict[str, Any]]:
        try:
            return await super().tools(force=force)
        except Exception:  # noqa: BLE001 - the app is stopped: list the tools without starting it
            if not self._catalog:
                self._catalog = self.cold_catalog()
            # look again soon, so the live catalogue replaces the cold one once the app is started
            self._fetched_at = time.monotonic() - self.refresh_tools_s + 5.0
            return self._catalog

    async def _prefetch(self) -> None:
        await self.tools(force=True)

    def message(self, template: str, **extra: Any) -> str:
        text = super().message(template, **extra)
        if template == NOT_RUNNING:
            text += " The bridge does not start it: use Start on Darwin's card in the Hoard Hub."
        return text


def build_bridge() -> DarwinBridge:
    return DarwinBridge(app="darwin", service="darwins-hoard", package="darwin_hoard", default_port=5233, data_dir_env="DARWIN_DATA_DIR",
                        title="Darwin's Hoard", root=__file__, default_timeout=300.0, autostart=False)


def main() -> int:
    build_bridge().run_bridge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
