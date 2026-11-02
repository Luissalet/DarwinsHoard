"""Stdio MCP bridge for Darwin's Hoard.

It never opens the database itself: every tool call is proxied to the running app (`POST /api/agent/call`) with the
Bearer token from `<DATA_DIR>/mcp-token`; the tool list comes from `GET /api/agent/tools`. When nothing answers, the
bridge starts the app (`python -m darwin_hoard`) and waits for it; DARWIN_BRIDGE_AUTOSTART=0 turns that off."""

from __future__ import annotations

import sys

from darwin_hoard.hoard_link.bridge import CatalogBridge


def main() -> int:
    CatalogBridge(app="darwin", service="darwins-hoard", package="darwin_hoard", default_port=5233, data_dir_env="DARWIN_DATA_DIR",
                  title="Darwin's Hoard", root=__file__, default_timeout=300.0).run_bridge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
