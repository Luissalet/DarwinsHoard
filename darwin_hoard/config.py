"""Process configuration (environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_ID, DEFAULT_PORT
from .hoard_link.appconfig import AppPaths, env_int, env_str
from .hoard_link.guard import parse_allowed_hosts

REPO_ROOT = Path(__file__).resolve().parent.parent
HOARDS_ROOT = REPO_ROOT.parent.parent  # .../IA/Hoards (Faustusables and Faustusnt live under it)


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    port: int = DEFAULT_PORT
    allowed_hosts: tuple[str, ...] = ()
    data_dir_configured: bool = False
    hub_url: str = "http://127.0.0.1:8810"
    hoards_root: Path = HOARDS_ROOT
    faustus_dir: Path = field(default_factory=lambda: HOARDS_ROOT.parent / "Faustus")

    @property
    def paths(self) -> AppPaths:
        return AppPaths(APP_ID, REPO_ROOT, self.data_dir, self.data_dir_configured)

    @property
    def token_path(self) -> Path:
        return self.paths.token_path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "darwin.db"

    @classmethod
    def from_env(cls) -> "Config":
        data_env = env_str("DARWIN_DATA_DIR")
        cfg = cls(
            data_dir=Path(data_env).expanduser() if data_env else REPO_ROOT / "data",
            port=env_int("DARWIN_PORT", default=DEFAULT_PORT) or DEFAULT_PORT,
            allowed_hosts=tuple(parse_allowed_hosts(os.environ.get("DARWIN_ALLOWED_HOSTS", ""))),
            data_dir_configured=bool(data_env),
            hub_url=(env_str("DARWIN_HUB_URL") or "http://127.0.0.1:8810").rstrip("/"),
        )
        if env_str("DARWIN_HOARDS_ROOT"):
            cfg.hoards_root = Path(env_str("DARWIN_HOARDS_ROOT"))
        if env_str("DARWIN_FAUSTUS_DIR"):
            cfg.faustus_dir = Path(env_str("DARWIN_FAUSTUS_DIR"))
        return cfg
