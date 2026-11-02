"""`python -m darwin_hoard` - run the app with uvicorn on 127.0.0.1 (the shared Hoard Link launcher)."""

from __future__ import annotations

from . import DEFAULT_PORT, SERVICE
from .hoard_link.service import run_main


def main() -> int:
    return run_main(service=SERVICE, package="darwin_hoard", default_port=DEFAULT_PORT, app_factory="darwin_hoard.main:create_app",
                    data_dir_env="DARWIN_DATA_DIR", port_env="DARWIN_PORT", open_browser_default=False, title="Darwin's Hoard")


if __name__ == "__main__":
    raise SystemExit(main())
