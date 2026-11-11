"""Everything the app runs, built once per process: the store, the importers, the tree and the agent token."""

from __future__ import annotations

import logging
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .config import Config
from .hoard_link.atomic import read_json, write_json_atomic
from .hoard_link.tokens import read_or_create_token
from . import reconcile, suit_seeds
from .legacy import LegacyImporter
from .store import Store
from .tree import TreeBuilder

log = logging.getLogger("darwin")

DEFAULT_SETTINGS: dict[str, Any] = {
    "whatsapp_account": "luis",
    "whatsapp_chat": "",                 # exact JID of the «Gittrend» chat; empty = not synced
    "whatsapp_chat_name": "",            # its display name, for the page
    "whatsapp_sync_minutes": 0,      # 0 = only on demand
    "inspiration_dir": r"E:\Development\IA\Research\inspiration",
    "radar_ideas": r"E:\Development\IA\Research\claude\radar-ideas.md",
    "faustus_url": "http://127.0.0.1:7000",
    "tree_refresh_minutes": 60,
    "brain_vault_dir": "",              # Faustus's Brain vault; empty = <Faustus>/data/brain/vault
    "brain_owner": "auto",              # Faustus user whose vault receives Notes/Darwin; auto = shared vault when Faustus has no login, else admin
    "brain_export_minutes": 360,        # 0 = only on demand
    "watches_check_minutes": 240,       # saved questions («avísame cuando…»); 0 = only on demand
    "watches_notify": True,             # a family notification when a saved question has news
    "repo_aliases": {},                 # old repository name → {"repo"|"path", "subdir", "search"}; adds to repo_map.BUILTIN_ALIASES
}


#: Old repository names (renames, apps folded into others) live in ``repo_map.BUILTIN_ALIASES``.


class Services:
    def __init__(self, config: Config):
        self.config = config
        config.paths.ensure()
        self.token = read_or_create_token(config.token_path)
        self.store = Store(config.db_path)
        self.store.recanonicalize()  # cheap; keeps old sources in step with canonical_url changes
        suit_seeds.seed(self.store)  # the six suits of proposal 36, once
        self.settings_path = config.data_dir / "settings.json"
        self.settings = {**DEFAULT_SETTINGS, **(read_json(self.settings_path, default={}) or {})}
        self.importer = LegacyImporter(self.store)
        self.ocr_job: dict[str, Any] = {"running": False}
        self.triage_job: dict[str, Any] = {"running": False}
        self.posts_job: dict[str, Any] = {"running": False}
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
                if time.time() - (self.store.get_meta("links_imported_at", 0) or 0) > 60 * 60 * 6:
                    try:
                        self.import_links()
                    except Exception:  # noqa: BLE001 - Links closed: try again next period
                        self.store.set_meta("links_imported_at", time.time())
                brain_every = int(self.settings.get("brain_export_minutes") or 0)
                if brain_every and time.time() - (self.store.get_meta("brain_exported_at", 0) or 0) > 60 * max(15, brain_every):
                    try:
                        self.brain_export()
                    except FileNotFoundError:
                        self.store.set_meta("brain_exported_at", time.time())  # no vault here: try again next period
                watch_every = int(self.settings.get("watches_check_minutes") or 0)
                if watch_every and time.time() - (self.store.get_meta("watches_checked_at", 0) or 0) > 60 * max(30, watch_every):
                    self.check_watches()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("tree refresh")
            self._stop.wait(300)

    # ------------------------------------------------------------------ actions

    def tree_builder(self) -> TreeBuilder:
        return TreeBuilder(self.store, hub_url=self.config.hub_url, faustus_url=self._faustus_base(),
                           hoards_root=self.config.hoards_root)

    def refresh_tree(self) -> dict[str, Any]:
        with self._tree_lock:
            report = self.tree_builder().refresh()
        reconcile.reconcile(self.store, by="tree")  # a changed tree can add or remove the proof a flag rests on
        return report

    def import_legacy(self, *, inspiration_dir: str = "", radar_ideas: str = "", agora: bool = True) -> dict[str, Any]:
        return self.importer.import_all(inspiration_dir=Path(inspiration_dir or self.settings["inspiration_dir"]),
                                        radar_ideas=Path(radar_ideas or self.settings["radar_ideas"]),
                                        hub_url=self.config.hub_url, agora=agora, hoards_root=Path(self.config.hoards_root),
                                        extra_objectives=self.log_objectives())

    def log_objectives(self) -> list[tuple[Path, str]]:
        """Objective logs outside the Hoards folder that also say what is wanted: Faustus's own."""
        path = Path(self.config.faustus_dir) / "OBJETIVOS.md"
        return [(path, "faustus")] if path.is_file() else []

    def import_gaps(self, *, use_model: bool = True, days: int = 0, max_new: int = 0) -> dict[str, Any]:
        """Gaps from every OBJETIVOS.md (lists and the long logs of Faustus and Writer); the local model sorts done from pending."""
        from . import gaps, gaps_log
        from .hoard_link import family
        lock = self._sync_locks.setdefault("gaps_import", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True}
        try:
            return gaps.import_objectives(self.store, Path(self.config.hoards_root), extra_files=self.log_objectives(),
                                          chat=family.chat if use_model else None, days=days or gaps_log.DEFAULT_DAYS,
                                          max_new=max_new or gaps_log.MAX_NEW_PER_RUN)
        finally:
            lock.release()

    # ------------------------------------------------------------------ ingestion (darwin_ingest, by Codex)

    def repo_map(self) -> "RepoMap":
        """The hub's repository inventory, the Ágora spaces' workspaces, Faustus and the aliases (built-in + settings)."""
        from .repo_map import RepoMap
        from .tree import _get
        hub: dict[str, str] = {}
        spaces: dict[str, str] = {}
        try:
            for rp in _get(f"{self.config.hub_url}/api/repos", timeout=30).get("repos", []):
                if rp.get("name") and rp.get("path"):
                    hub[rp["name"]] = rp["path"]
        except Exception:  # noqa: BLE001
            log.info("hub repos not available")
        try:
            for sp in _get(f"{self.config.hub_url}/api/agora/spaces").get("spaces", []):
                if sp.get("workspace"):
                    spaces[sp["id"]] = sp["workspace"]
        except Exception:  # noqa: BLE001 - the hub may be down; Faustus alone still works
            log.info("hub not answering: verifying only Faustus deliveries")
        return RepoMap(hub_repos=hub, faustus_dir=str(self.config.faustus_dir), spaces=spaces,
                       custom=self.settings.get("repo_aliases") or {})

    def repo_roots(self) -> dict[str, Any]:
        """Local repository (and subfolder, for an app folded into another) of each delivery ``repo`` value, plus every
        hub repository and Ágora space. A name found nowhere is reported as «repository_not_mapped»."""
        names = [r["repo"] for r in self.store.q("SELECT DISTINCT repo FROM deliveries WHERE repo IS NOT NULL")]
        return self.repo_map().roots(names)

    def repo_aliases(self) -> dict[str, Any]:
        counts = {r["repo"]: r["n"] for r in self.store.q("SELECT repo, COUNT(*) AS n FROM deliveries WHERE repo IS NOT NULL GROUP BY repo")}
        rmap = self.repo_map()
        names = sorted(counts)
        unresolved = [n for n in names if rmap.resolve(n) is None]
        return {"aliases": rmap.table(counts), "unresolved": [{"name": n, "deliveries": counts[n]} for n in unresolved],
                "repositories": sorted(rmap.hub)}

    def set_repo_alias(self, name: str, *, repo: str = "", path: str = "", subdir: str = "", search: bool = False,
                       remove: bool = False) -> dict[str, Any]:
        """Luis's own alias (saved in settings ``repo_aliases``); ``remove`` drops his entry (built-in ones come back)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required")
        aliases = dict(self.settings.get("repo_aliases") or {})
        if remove:
            aliases.pop(name, None)
        else:
            if not (repo or path or search):
                raise ValueError("give repo, path or search")
            aliases[name] = {k: v for k, v in {"repo": repo.strip(), "path": path.strip(), "subdir": subdir.strip().strip("/\\"),
                                               "search": bool(search)}.items() if v}
        self.update_settings({"repo_aliases": aliases})
        return self.repo_aliases()

    def fix_delivery(self, delivery_id: int, *, repo: str = "", commit_sha: str = "", agora_task: int = 0, note: str = "",
                     by: str = "agent", clear_commit: bool = False) -> dict[str, Any]:
        """Correct the repository, commit or Ágora task a delivery declared (a rewritten history, a wrong repository) and check
        that delivery again. The declared values are kept in ``declared`` and every change goes to the history."""
        from darwin_ingest import verify_deliveries
        from .errors import DarwinError
        row = self.store.one("SELECT * FROM deliveries WHERE id=?", (int(delivery_id),))
        if not row:
            raise DarwinError("not_found", f"No delivery {delivery_id}.")
        repo, commit_sha = (repo or "").strip(), re.sub(r"\s+", " ", (commit_sha or "").strip())
        if not (repo or commit_sha or agora_task or clear_commit):
            raise DarwinError("invalid", "Give repo, commit_sha, agora_task or clear_commit.")
        if clear_commit and commit_sha:
            raise DarwinError("invalid", "clear_commit and commit_sha exclude each other.")
        if commit_sha and not re.fullmatch(r"[0-9a-fA-F]{7,40}(?:[ ,]+[0-9a-fA-F]{7,40})*", commit_sha):
            raise DarwinError("invalid", f"«{commit_sha}» is not a commit id (7-40 hex digits, several separated by commas).")
        changes = {k: v for k, v in (("repo", repo), ("commit_sha", commit_sha), ("agora_task", int(agora_task) or None)) if v}
        if clear_commit and row.get("commit_sha"):
            changes["commit_sha"] = None  # the commit belonged to another task: the delivery has none of its own
        changes = {k: v for k, v in changes.items() if str(row.get(k) or "") != str(v if v is not None else "")}
        declared = row.get("declared") if isinstance(row.get("declared"), dict) else {}
        if changes:
            now = time.time()
            with self.store.tx() as c:
                kept = dict(declared)
                prior = kept.setdefault("declared_before_fix", {})
                for k, v in changes.items():
                    prior.setdefault(k, row.get(k))
                    c.execute(f"UPDATE deliveries SET {k}=?, updated=? WHERE id=?", (v, now, row["id"]))
                    c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('deliveries',?,?,?,?,?,?,?)",
                              (row["id"], k, str(row.get(k) or ""), "" if v is None else str(v), now, by, note[:1000]))
                c.execute("UPDATE deliveries SET declared=? WHERE id=?", (json.dumps(kept, ensure_ascii=False), row["id"]))
        result = verify_deliveries(self.store, self.repo_roots(), agora_lookup=self._agora_task, ids=[row["id"]])
        after = self.store.one("SELECT id, repo, commit_sha, agora_task, implementation, evidence FROM deliveries WHERE id=?", (row["id"],))
        proof = ((after.get("evidence") or {}).get("commit_ancestry") or {}) if after else {}
        return {"id": row["id"], "changed": sorted(changes), "repo": after["repo"], "commit_sha": after["commit_sha"], "agora_task": after["agora_task"],
                "implementation": after["implementation"], "status": proof.get("status"), "reason": proof.get("reason"), "via": proof.get("via"),
                "checked": len(result["deliveries"]), "history": self.store.history_of("deliveries", row["id"])[-6:]}

    def _agora_task(self, task_id: int) -> dict[str, Any] | None:
        from .tree import _get
        return _get(f"{self.config.hub_url}/api/agora/tasks/{int(task_id)}", timeout=20)

    def verify_deliveries(self) -> dict[str, Any]:
        from darwin_ingest import verify_deliveries
        result = verify_deliveries(self.store, self.repo_roots(), agora_lookup=self._agora_task)
        summary: dict[str, int] = {}
        for r in result["deliveries"]:
            if r["status"] == "unknown":
                k = f"unknown:{r.get('reason', '')}"
            elif r["status"] == "integrated" and r.get("via") not in (None, "direct"):
                k = f"integrated:{r['via']}"
            else:
                k = r["status"]
            summary[k] = summary.get(k, 0) + 1
        self.store.set_meta("deliveries_verified_at", time.time())
        return {"summary": summary, "checked": len(result["deliveries"]), "verified_at": time.time()}

    def _faustus_base(self) -> str:
        """Where Faustus answers now: the Hub may have moved it to a Spark ("Run on"), and WhatsApp's session travels
        with it, so the configured address on this PC would read a stopped copy. Asked of the Hub at most once a minute."""
        import json as _json
        import os
        import urllib.request
        configured = str(self.settings.get("faustus_url") or "http://127.0.0.1:7000").rstrip("/")
        cache = getattr(self, "_placement_cache", None)
        if cache and time.time() - cache[0] < 60:
            return cache[1] or configured
        moved = ""
        hub = (os.environ.get("HOARD_HUB_URL") or "http://127.0.0.1:8810").rstrip("/")
        try:
            with urllib.request.urlopen(f"{hub}/api/placement", timeout=5) as r:
                data = _json.loads(r.read().decode("utf-8"))
            if data.get("location") == "sparks" and not (data.get("job") or {}).get("running"):
                url = str((data.get("urls") or {}).get("faustus") or "")
                moved = url.rstrip("/") if url.startswith(("http://", "https://")) else ""
        except Exception:  # noqa: BLE001 - no Hub: the configured address
            moved = ""
        self._placement_cache = (time.time(), moved)
        return moved or configured

    def _faustus_get(self, path: str, params: dict[str, Any]) -> Any:
        import json as _json
        import urllib.parse
        import urllib.request
        url = f"{self._faustus_base()}{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return _json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            body = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Faustus answered {exc.code}: {body}") from exc

    def _faustus_post(self, path: str, body: Optional[dict[str, Any]] = None, timeout: float = 60) -> Any:
        import json as _json
        import urllib.request
        url = f"{self._faustus_base()}{path}"
        req = urllib.request.Request(url, data=_json.dumps(body or {}).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            body_text = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Faustus answered {exc.code}: {body_text}") from exc

    @staticmethod
    def _bridge_down(exc: Exception) -> bool:
        text = str(exc).lower()
        return "whatsapp bridge" in text and "not running" in text

    def _start_whatsapp_bridge(self, wait_s: float = 45.0) -> dict[str, Any]:
        """Start Faustus's WhatsApp bridge and wait until it is connected (and done catching up, when it says so)."""
        started = self._faustus_post("/api/whatsapp/start", {}, timeout=60)
        status: dict[str, Any] = {}
        deadline = time.time() + wait_s
        while time.time() < deadline:
            try:
                status = self._faustus_get("/api/whatsapp/status", {})
            except Exception:  # noqa: BLE001
                status = {}
            sync = status.get("sync") or {}
            if status.get("status") == "connected" and not sync.get("active"):
                break
            if status.get("status") in ("qr", "logged_out"):
                break
            time.sleep(2)
        self.store.set_meta("whatsapp_bridge_started_at", time.time())
        return {"started": bool(started.get("started", True)), "status": status.get("status") or "unknown"}

    def whatsapp_chats(self, query: str = "") -> list[dict[str, Any]]:
        try:
            data = self._faustus_get("/api/whatsapp/chats", {"limit": 200})
        except RuntimeError as exc:
            if not self._bridge_down(exc):
                raise
            self._start_whatsapp_bridge()
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
            bridge: dict[str, Any] = {}
            for _ in range(max(1, max_pages)):
                try:
                    last = sync_whatsapp_page(self.store, client, account=account, chat=chat)
                except RuntimeError as exc:
                    # The bridge stops with Faustus or a crash and nobody notices for days: start it and read again.
                    if bridge or not self._bridge_down(exc):
                        raise
                    bridge = self._start_whatsapp_bridge()
                    last = sync_whatsapp_page(self.store, client, account=account, chat=chat)
                totals["created"] += last["created"]
                totals["existing"] += last["existing"]
                totals["sources"].update(last["sources"])
                totals["pages"] += 1
                if last["pass_complete"]:
                    break
            self.store.set_meta("whatsapp_last_sync", time.time())
            if totals["created"]:
                self.start_ocr()    # new screenshots: read them in the background
                self.start_posts()  # new post links: read them through Links' sessions
            out = {"chat": chat, "pages": totals["pages"], "created": totals["created"], "existing": totals["existing"],
                   "sources": len(totals["sources"]), "pass_complete": last.get("pass_complete"), "coverage": last.get("coverage")}
            if bridge:
                out["bridge_started"] = bridge
            return out
        finally:
            lock.release()

    def _hub_io(self):
        from .hoard_link import family
        from .hoard_link._hubclient import fetch_detailed
        return family._hub(), family._headers(), fetch_detailed

    def discuss(self, proposal_id: int, note: str = "") -> dict[str, Any]:
        from . import debate
        hub, headers, fetch = self._hub_io()
        return debate.discuss(self.store, proposal_id, hub, headers, fetch, note=note)

    def proposal_thread(self, proposal_id: int) -> dict[str, Any]:
        from . import debate
        hub, headers, fetch = self._hub_io()
        return debate.thread(self.store, proposal_id, hub, headers, fetch)

    def import_links(self) -> dict[str, Any]:
        from . import links_import
        result = links_import.import_links(self.store, self.links_call)
        self.store.set_meta("links_imported_at", time.time())
        return result

    def brain_export(self) -> dict[str, Any]:
        from . import brain_export
        base = Path(self.settings.get("brain_vault_dir") or Path(self.config.faustus_dir) / "data" / "brain" / "vault")
        owner = str(self.settings.get("brain_owner") or "auto")
        if owner == "auto":
            try:
                status = self._faustus_get("/api/auth/status", {})
            except Exception:  # noqa: BLE001 - Faustus closed: its usual single-user setup
                status = {}
            owner = "_shared" if status.get("auth_disabled") or not status.get("auth_enabled", True) else "admin"
        owner = re.sub(r'[<>:"/\\|?*]+', "_", owner)[:60]
        if not base.exists():
            raise FileNotFoundError(f"Faustus's Brain vault is not at {base} (set brain_vault_dir).")
        result = brain_export.export(self.store, base / owner)
        result["owner"] = owner
        self.store.set_meta("brain_exported_at", time.time())
        return result

    def _translate(self, gaps: list[dict[str, Any]]) -> dict[int, str]:
        from . import radar
        from .hoard_link import family
        return radar.translate_with(family.chat, gaps)

    def radar_plan(self, *, limit: int = 10, remember: bool = True) -> dict[str, Any]:
        from . import radar
        return radar.plan(self.store, limit=limit, remember=remember, translate=self._translate)

    def radar_run(self, *, top: int = 3, per_gap: int = 5, add: bool = False, gap_ids: list[int] | None = None,
                  web: bool = False) -> dict[str, Any]:
        from . import radar
        return radar.run(self.store, top=top, per_gap=per_gap, add=add, gap_ids=gap_ids, translate=self._translate, web=web)

    def check_watches(self) -> dict[str, Any]:
        """Ask every saved question again; with news (and ``watches_notify``), one family notification per question."""
        from . import watches
        result = watches.check_all(self.store)
        if self.settings.get("watches_notify", True):
            from .hoard_link import fam_notify
            for w in result["with_news"]:
                n = w["news"]
                parts = [f"{len(n.get('discoveries', []))} descubrimientos nuevos" if n.get("discoveries") else "",
                         f"{len(n.get('state_changes', []))} cambios de estado" if n.get("state_changes") else "",
                         ("apps: " + ", ".join(n["apps"])) if n.get("apps") else ""]
                try:
                    w["notified"] = fam_notify.notify(f"Darwin: {w['question']}", " · ".join(p for p in parts if p),
                                                      url=f"http://127.0.0.1:{self.config.port}/#research", group="darwin-watches",
                                                      dedupe_key=f"darwin-watch-{w['id']}-{int(time.time() // 3600)}").get("ok", False)
                except Exception:  # noqa: BLE001 - the hub may be closed: the news stays on the page
                    w["notified"] = False
        return result

    def ask(self, question: str) -> dict[str, Any]:
        from . import ask as asker
        from .hoard_link import family
        return asker.ask(self.store, question, chat=family.chat)

    # ------------------------------------------------------------------ social posts (through Links' signed-in sessions)

    def links_call(self, app: str, tool: str, arguments: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        """Call a tool of another Hoard through the hub; if the app is not running, ask the hub to start it and retry once."""
        from .hoard_link import family
        res = family.call(app, tool, arguments, timeout=timeout)
        refused = not res.get("ok") and any(w in str(res.get("error") or "") for w in ("refused", "10061", "not running", "unreachable"))
        if refused:
            hub, headers, fetch = self._hub_io()
            fetch(f"{hub}/api/apps/{app}/start", {}, method="POST", timeout=20.0, headers=headers)
            deadline = time.time() + 45
            while time.time() < deadline:
                time.sleep(2)
                res = family.call(app, tool, arguments, timeout=timeout)
                if res.get("ok") or not any(w in str(res.get("error") or "") for w in ("refused", "10061", "not running", "unreachable")):
                    break
        return res

    def accounts(self) -> dict[str, Any]:
        res = self.links_call("links", "site_sessions", {}, timeout=20.0)
        body = res.get("result") if isinstance(res.get("result"), dict) else {}
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "Links did not answer", "sites": []}
        keep = {"x", "instagram", "threads", "tiktok", "reddit", "facebook", "youtube"}
        return {"ok": True, "browser": (body.get("browser") or {}).get("name"), "active": body.get("active"),
                "sites": [s for s in body.get("sites") or [] if s.get("id") in keep]}

    def account_login(self, site: str, *, finish: bool = False, cancel: bool = False) -> dict[str, Any]:
        res = self.links_call("links", "site_login", {"site": site, "finish": finish, "cancel": cancel}, timeout=40.0)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or json.dumps(res.get("result") or {}, ensure_ascii=False)[:300])
        return self.accounts()

    def read_posts(self, *, limit: int = 30) -> dict[str, Any]:
        from . import social
        from .hoard_link import family
        lock = self._sync_locks.setdefault("posts", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True, **self.posts_job}
        try:
            self.posts_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
            result = social.read_posts(self.store, self.links_call, limit=limit,
                                       on_progress=lambda d, t: self.posts_job.update(done=d, total=t))
            self.posts_job = {"running": False, "finished": time.time(), **result}
            return result
        except Exception as exc:  # noqa: BLE001
            self.posts_job = {"running": False, "finished": time.time(), "error": str(exc)}
            raise
        finally:
            lock.release()

    def start_posts(self, *, limit: int = 30) -> dict[str, Any]:
        if self.posts_job.get("running"):
            return dict(self.posts_job)
        self.posts_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
        threading.Thread(target=lambda: self._safe(self.read_posts, limit=limit), name="darwin-posts", daemon=True).start()
        return dict(self.posts_job)

    def triage(self, *, channel: str = "", limit: int = 50) -> dict[str, Any]:
        """Suggest an app for discoveries without proposals (see :mod:`triage`); one run at a time."""
        from . import triage as triager
        from .hoard_link import family
        lock = self._sync_locks.setdefault("triage", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True, **self.triage_job}
        try:
            self.triage_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
            result = triager.run(self.store, family.chat, channel=channel, limit=limit,
                                 on_progress=lambda d, t: self.triage_job.update(done=d, total=t))
            self.triage_job = {"running": False, "finished": time.time(), **result}
            return result
        except Exception as exc:  # noqa: BLE001 - surfaced to the page
            self.triage_job = {"running": False, "finished": time.time(), "error": str(exc)}
            raise
        finally:
            lock.release()

    def start_triage(self, *, channel: str = "", limit: int = 50) -> dict[str, Any]:
        if self.triage_job.get("running"):
            return dict(self.triage_job)
        self.triage_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
        threading.Thread(target=lambda: self._safe(self.triage, channel=channel, limit=limit), name="darwin-triage", daemon=True).start()
        return dict(self.triage_job)

    # ------------------------------------------------------------------ screenshots (OCR)

    @property
    def faustus_media_dir(self) -> Path:
        return Path(self.config.faustus_dir) / "data" / "whatsapp" / "media"

    @property
    def media_dir(self) -> Path:
        """Darwin's own copy of the chat's pictures: the bridge keeps them where Faustus runs, which may be a Spark."""
        path = Path(self.config.db_path).parent / "whatsapp-media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_media(self, raw: str) -> Optional[Path]:
        """The attachment in Darwin's copy, taken from this PC's Faustus folder or downloaded from the Faustus that runs
        now (``/api/whatsapp/media/<name>``). None when neither has it."""
        import shutil
        import urllib.parse
        import urllib.request
        from . import ocr
        name = ocr.attachment_name(raw)
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        target = self.media_dir / name
        if target.is_file():
            return target
        local = self.faustus_media_dir / name
        try:
            if local.is_file():
                shutil.copy2(local, target)
                return target
        except OSError:
            pass
        url = f"{self._faustus_base()}/api/whatsapp/media/{urllib.parse.quote(name)}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            if data:
                tmp = target.with_suffix(target.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(target)
                return target
        except Exception:  # noqa: BLE001 - not there (yet): the OCR marks it missing
            return None
        return None

    def _prefetch_media(self, limit: int) -> int:
        """Bring the pictures the OCR is about to read, and give a second chance to those it marked missing before."""
        rows = self.store.q("SELECT id, attachment, declared FROM captures WHERE attachment IS NOT NULL "
                            "AND attachment NOT IN ('', '\"\"') ORDER BY at DESC LIMIT ?", (limit * 4,))
        got = 0
        for row in rows:
            declared = row.get("declared") or {}
            if isinstance(declared, str):
                declared = json.loads(declared or "{}")
            ocr_state = declared.get("ocr")
            retry = isinstance(ocr_state, dict) and ocr_state.get("error") == "image file not found"
            if ocr_state and not retry:
                continue
            if self.ensure_media(row.get("attachment") or "") is None:
                continue
            got += 1
            if retry:
                self.store.drop_capture_declared(row["id"], "ocr")
        return got

    def ocr_inbox(self, *, limit: int = 60) -> dict[str, Any]:
        """Read the unread screenshots of the inbox with the family's OCR and link what they show (see :mod:`ocr`)."""
        from . import ocr
        from .hoard_link import fam_docs
        lock = self._sync_locks.setdefault("ocr", threading.Lock())
        if not lock.acquire(blocking=False):
            return {"busy": True, **self.ocr_job}
        try:
            self.ocr_job = {"running": True, "done": 0, "total": 0, "started": time.time()}
            try:
                self._prefetch_media(limit)
            except Exception:  # noqa: BLE001 - the OCR still reads what is already here
                log.exception("media prefetch")

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
