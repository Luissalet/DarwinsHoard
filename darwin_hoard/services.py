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
    "whatsapp_account": "luis",
    "whatsapp_chat": "",            # exact JID of the «Gittrend» chat; empty = not synced
    "whatsapp_sync_minutes": 0,      # 0 = only on demand
    "inspiration_dir": r"D:\LocalAI\inspiration",
    "radar_ideas": r"E:\Development\IA\Research\claude\radar-ideas.md",
    "faustus_url": "http://127.0.0.1:7000",
    "tree_refresh_minutes": 60,
}


#: Names the Ágora used before repositories were renamed or merged, mapped to today's name in the hub's inventory.
REPO_ALIASES = {"hoardlink": "Hoard Hub", "fielddex": "Hoard Dex", "taloshoard": "Talos's Hoard", "bloodarrows": "Blood Arrows",
                "writershoard": "Writers hoard desktop", "gamerhoard": "Gamer Hoard", "cookhoard": "Cook Hoard", "homehoard": "Home Hoard"}


def _repo_norm(name: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", str(name).lower().replace("'s", ""))


class Services:
    def __init__(self, config: Config):
        self.config = config
        config.paths.ensure()
        self.token = read_or_create_token(config.token_path)
        self.store = Store(config.db_path)
        self.store.recanonicalize()  # cheap; keeps old sources in step with canonical_url changes
        self.settings_path = config.data_dir / "settings.json"
        self.settings = {**DEFAULT_SETTINGS, **(read_json(self.settings_path, default={}) or {})}
        self.importer = LegacyImporter(self.store)
        self.ocr_job: dict[str, Any] = {"running": False}
        self.started = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tree_lock = threading.Lock()
        self._sync_locks: dict[str, threading.Lock] = {}

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
                every = int(self.settings.get("whatsapp_sync_minutes") or 0)
                if every and self.settings.get("whatsapp_chat"):
                    last_sync = self.store.get_meta("whatsapp_last_sync", 0) or 0
                    if time.time() - last_sync > 60 * max(5, every):
                        self.sync_whatsapp()
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

    # ------------------------------------------------------------------ ingestion (darwin_ingest, by Codex)

    def repo_roots(self) -> dict[str, str]:
        """Local repository of each delivery ``repo`` value: the hub's repository inventory (by name, with the old names
        the Ágora still uses), the Ágora spaces' workspaces and Faustus. Keys are the exact ``repo`` values found."""
        from .tree import _get
        known: dict[str, str] = {"faustus": str(self.config.faustus_dir)}
        try:
            for rp in _get(f"{self.config.hub_url}/api/repos", timeout=30).get("repos", []):
                if rp.get("name") and rp.get("path"):
                    known[_repo_norm(rp["name"])] = rp["path"]
        except Exception:  # noqa: BLE001
            log.info("hub repos not available")
        for old, new in REPO_ALIASES.items():
            if _repo_norm(new) in known:
                known.setdefault(old, known[_repo_norm(new)])
        roots = {"Faustus": str(self.config.faustus_dir), "faustus": str(self.config.faustus_dir)}
        for row in self.store.q("SELECT DISTINCT repo FROM deliveries WHERE repo IS NOT NULL"):
            path = known.get(_repo_norm(row["repo"]))
            if path:
                roots[row["repo"]] = path
        try:
            for sp in _get(f"{self.config.hub_url}/api/agora/spaces").get("spaces", []):
                if sp.get("workspace"):
                    roots.setdefault(sp["id"], sp["workspace"])
        except Exception:  # noqa: BLE001 - the hub may be down; Faustus alone still works
            log.info("hub not answering: verifying only Faustus deliveries")
        # Only folders that are a repository themselves: a workspace like D:\LocalAI is not, and git would walk the
        # whole tree on every call. A delivery whose repo is not here is reported as «repository_not_mapped».
        return {k: v for k, v in roots.items() if (Path(v) / ".git").exists()}

    def verify_deliveries(self) -> dict[str, Any]:
        from darwin_ingest import verify_deliveries
        result = verify_deliveries(self.store, self.repo_roots())
        summary: dict[str, int] = {}
        for r in result["deliveries"]:
            k = r["status"] if r["status"] != "unknown" else f"unknown:{r.get('reason', '')}"
            summary[k] = summary.get(k, 0) + 1
        self.store.set_meta("deliveries_verified_at", time.time())
        return {"summary": summary, "checked": len(result["deliveries"]), "verified_at": time.time()}

    def _faustus_get(self, path: str, params: dict[str, Any]) -> Any:
        import json as _json
        import urllib.parse
        import urllib.request
        url = f"{self.settings['faustus_url'].rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return _json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            body = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Faustus answered {exc.code}: {body}") from exc

    def whatsapp_chats(self, query: str = "") -> list[dict[str, Any]]:
        data = self._faustus_get("/api/whatsapp/chats", {"limit": 200})
        chats = data.get("chats", data) if isinstance(data, dict) else data
        q = query.lower().strip()
        return [c for c in chats if not q or q in str(c.get("name") or c.get("chat_name") or "").lower() or q in str(c.get("jid") or c.get("id") or "")]

    def sync_whatsapp(self, *, chat: str = "", account: str = "", max_pages: int = 50) -> dict[str, Any]:
        """Read the chosen chat page by page through Faustus's bridge (read only). One sync per account/chat at a time."""
        from darwin_ingest import sync_whatsapp_page
        chat = chat or self.settings.get("whatsapp_chat") or ""
        account = account or self.settings.get("whatsapp_account") or "luis"
        if "@" not in chat:
            raise ValueError("Choose the chat first (its exact JID, e.g. 1203…@g.us): darwin_whatsapp_chats lists them.")
        lock = self._sync_locks.setdefault(f"{account}|{chat}", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True, "chat": chat}
        try:
            def client(*, chat: str, cursor: str, limit: int) -> dict[str, Any]:
                return self._faustus_get("/api/whatsapp/message-page", {"chat": chat, "cursor": cursor, "limit": limit})
            totals = {"created": 0, "existing": 0, "sources": set(), "pages": 0}
            last: dict[str, Any] = {}
            for _ in range(max(1, max_pages)):
                last = sync_whatsapp_page(self.store, client, account=account, chat=chat)
                totals["created"] += last["created"]
                totals["existing"] += last["existing"]
                totals["sources"].update(last["sources"])
                totals["pages"] += 1
                if last["pass_complete"]:
                    break
            self.store.set_meta("whatsapp_last_sync", time.time())
            if totals["created"]:
                self.start_ocr()  # new screenshots: read them in the background
            return {"chat": chat, "pages": totals["pages"], "created": totals["created"], "existing": totals["existing"],
                    "sources": len(totals["sources"]), "pass_complete": last.get("pass_complete"), "coverage": last.get("coverage")}
        finally:
            lock.release()

    # ------------------------------------------------------------------ screenshots (OCR)

    @property
    def media_dir(self) -> Path:
        return Path(self.config.faustus_dir) / "data" / "whatsapp" / "media"

    def ocr_inbox(self, *, limit: int = 60) -> dict[str, Any]:
        """Read the unread screenshots of the inbox with the family's OCR and link what they show (see :mod:`ocr`)."""
        from . import ocr
        from .hoard_link import fam_docs
        lock = self._sync_locks.setdefault("ocr", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True, **self.ocr_job}
        try:
            self.ocr_job = {"running": True, "done": 0, "total": 0, "started": time.time()}

            def progress(done: int, total: int) -> None:
                self.ocr_job.update(done=done, total=total)

            result = ocr.read_inbox(self.store, self.media_dir, lambda path: fam_docs.ocr_image(path, lang="en", timeout_s=180),
                                    limit=limit, on_progress=progress)
            self.ocr_job = {"running": False, "finished": time.time(), **result}
            return result
        except Exception as exc:  # noqa: BLE001 - surfaced to the page, never kills the app
            self.ocr_job = {"running": False, "finished": time.time(), "error": str(exc)}
            raise
        finally:
            lock.release()

    def start_ocr(self, *, limit: int = 60) -> dict[str, Any]:
        """The same in the background (the page polls ``ocr_job``)."""
        if self.ocr_job.get("running"):
            return dict(self.ocr_job)
        self.ocr_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
        threading.Thread(target=lambda: self._safe(self.ocr_inbox, limit=limit), name="darwin-ocr", daemon=True).start()
        return dict(self.ocr_job)

    @staticmethod
    def _safe(fn, **kwargs) -> None:
        try:
            fn(**kwargs)
        except Exception:  # noqa: BLE001 - recorded in ocr_job
            pass

    def ingest(self, records: list[dict[str, Any]], channel: str) -> dict[str, Any]:
        from darwin_ingest import ingest_batch
        return ingest_batch(self.store, records, channel=channel)

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
