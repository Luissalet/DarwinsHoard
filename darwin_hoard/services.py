"""Everything the app runs, built once per process: the store, the importers, the tree and the agent token."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .hoard_link.atomic import read_json, write_json_atomic
from .hoard_link.tokens import read_or_create_token
from .legacy import LegacyImporter
from .store import Store
from .tree import TreeBuilder

log = logging.getLogger("darwin")

DEFAULT_SETTINGS: dict[str, Any] = {
    "inspiration_dir": r"D:\LocalAI\inspiration",
    "radar_ideas": r"E:\Development\IA\Research\claude\radar-ideas.md",
    "faustus_url": "http://127.0.0.1:7000",
    "tree_refresh_minutes": 60,
}


class Services:
    def __init__(self, config: Config):
        self.config = config
        config.paths.ensure()
        self.token = read_or_create_token(config.token_path)
        self.store = Store(config.db_path)
        self.settings_path = config.data_dir / "settings.json"
        self.settings = {**DEFAULT_SETTINGS, **(read_json(self.settings_path, default={}) or {})}
        self.importer = LegacyImporter(self.store)
        self.started = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tree_lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    def start(self, background: bool = True) -> None:
        if background:
            self._thread = threading.Thread(target=self._loop, name="darwin-tree", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(5)
        while not self._stop.is_set():
            try:
                last = self.store.get_meta("tree_refreshed_at", 0) or 0
                if time.time() - last > 60 * max(5, int(self.settings["tree_refresh_minutes"])):
                    self.refresh_tree()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("tree refresh")
            self._stop.wait(300)

    # ------------------------------------------------------------------ actions

    def tree_builder(self) -> TreeBuilder:
        return TreeBuilder(self.store, hub_url=self.config.hub_url, faustus_url=self.settings["faustus_url"],
                           hoards_root=self.config.hoards_root)

    def refresh_tree(self) -> dict[str, Any]:
        with self._tree_lock:
            return self.tree_builder().refresh()

    def import_legacy(self, *, inspiration_dir: str = "", radar_ideas: str = "", agora: bool = True) -> dict[str, Any]:
        return self.importer.import_all(inspiration_dir=Path(inspiration_dir or self.settings["inspiration_dir"]),
                                        radar_ideas=Path(radar_ideas or self.settings["radar_ideas"]),
                                        hub_url=self.config.hub_url, agora=agora)

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                raise ValueError(f"Unknown setting: {key}")
            if value is not None:
                self.settings[key] = value
        write_json_atomic(self.settings_path, self.settings)
        return dict(self.settings)

    def health(self) -> dict[str, Any]:
        counts = self.store.counts()
        return {"sources": counts["sources"], "proposals": counts["proposals"], "capabilities": counts["capabilities"],
                "tree_refreshed_at": self.store.get_meta("tree_refreshed_at"), "version": __version__}
