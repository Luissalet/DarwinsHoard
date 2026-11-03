"""The Darwin store (SQLite, ``<data>/darwin.db``): one row per thing, every write idempotent by a key.

Genealogy: capture -> source -> idea -> proposal (idea x target) -> delivery (proposal x repo/commit) -> evidence, plus the
capability tree and the gaps. Four state axes are kept apart and never folded into one flag:

* proposal:        pendiente | investigando | debatida | aceptada | aplazada | descartada | cubierta
* implementation:  sin_implementar | parcial | integrada | sustituida      (per delivery: capability x target)
* verification:    documentada | probada | recomprobar | desconocida        (per delivery)
* operation:       disponible | detenida | desconocida                       (per capability node, from the hub)

``declared`` columns keep what a document or a person said, word for word; a state change goes through
:meth:`Store.set_state`, which writes the old value to ``history`` so nothing is overwritten silently.

Contract used by other packages (``darwin_ingest``): :meth:`add_capture` (idempotent on ``capture_key``),
:meth:`upsert_source`, :meth:`link_capture`, :meth:`upsert_proposal`, :meth:`upsert_delivery`, :meth:`set_state`."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .canon import canonical_url, repo_of, source_key

PROPOSAL_STATES = ("pendiente", "investigando", "debatida", "aceptada", "aplazada", "descartada", "cubierta")
IMPLEMENTATION_STATES = ("sin_implementar", "parcial", "integrada", "sustituida")
VERIFICATION_STATES = ("documentada", "probada", "recomprobar", "desconocida")
OPERATION_STATES = ("disponible", "detenida", "desconocida")
RELATIONS = ("inspirado_por", "codigo_de", "dependencia", "desconocida")
SOURCE_KINDS = ("repo", "article", "video", "paper", "post", "idea", "tool")
GAP_STATES = ("abierta", "resuelta", "descartada")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'repo', url TEXT, repo TEXT, github_id INTEGER,
  title TEXT, summary TEXT, license TEXT, stars TEXT, legacy_radar_no INTEGER, first_seen REAL, last_seen REAL,
  captures INTEGER NOT NULL DEFAULT 0, created REAL, updated REAL, meta TEXT);
CREATE INDEX IF NOT EXISTS sources_radar ON sources(legacy_radar_no);
CREATE TABLE IF NOT EXISTS source_aliases(alias TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS captures(
  id INTEGER PRIMARY KEY, capture_key TEXT NOT NULL UNIQUE, channel TEXT NOT NULL, source_id INTEGER REFERENCES sources(id),
  at REAL, author TEXT, chat TEXT, text TEXT, url TEXT, attachment TEXT, provenance TEXT, declared TEXT, created REAL);
CREATE INDEX IF NOT EXISTS captures_source ON captures(source_id);
CREATE INDEX IF NOT EXISTS captures_channel ON captures(channel, at);
CREATE TABLE IF NOT EXISTS capture_sources(capture_id INTEGER NOT NULL, source_id INTEGER NOT NULL, PRIMARY KEY(capture_id, source_id));
CREATE TABLE IF NOT EXISTS ideas(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, source_id INTEGER REFERENCES sources(id), title TEXT, benefit TEXT,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS proposals(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, source_id INTEGER REFERENCES sources(id), idea_id INTEGER REFERENCES ideas(id),
  target TEXT, capability_key TEXT, state TEXT NOT NULL DEFAULT 'pendiente', reason TEXT, origin TEXT,
  agora_space TEXT, agora_task INTEGER, agora_thread INTEGER, declared TEXT, created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS proposals_source ON proposals(source_id);
CREATE INDEX IF NOT EXISTS proposals_target ON proposals(target, state);
CREATE TABLE IF NOT EXISTS deliveries(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, proposal_id INTEGER REFERENCES proposals(id), source_id INTEGER REFERENCES sources(id),
  target TEXT, capability_key TEXT, repo TEXT, commit_sha TEXT, relation TEXT NOT NULL DEFAULT 'desconocida',
  implementation TEXT NOT NULL DEFAULT 'sin_implementar', verification TEXT NOT NULL DEFAULT 'desconocida', evidence TEXT,
  agora_space TEXT, agora_task INTEGER, declared TEXT, created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS deliveries_source ON deliveries(source_id);
CREATE TABLE IF NOT EXISTS capabilities(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, parent_key TEXT, level TEXT NOT NULL, name TEXT, app_id TEXT, detail TEXT,
  evidence TEXT NOT NULL DEFAULT 'declarada', operation TEXT NOT NULL DEFAULT 'desconocida', since REAL, seen REAL, meta TEXT);
CREATE INDEX IF NOT EXISTS capabilities_parent ON capabilities(parent_key);
CREATE INDEX IF NOT EXISTS capabilities_app ON capabilities(app_id);
CREATE TABLE IF NOT EXISTS gaps(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, detail TEXT, target TEXT, capability_key TEXT, state TEXT NOT NULL DEFAULT 'abierta',
  watch TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY, entity TEXT NOT NULL, entity_id INTEGER NOT NULL, field TEXT NOT NULL, old TEXT, new TEXT,
  at REAL NOT NULL, by TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS history_entity ON history(entity, entity_id);
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, name TEXT, file TEXT, sha256 TEXT, at REAL, counts TEXT);
CREATE TABLE IF NOT EXISTS capability_backing(
  capability_key TEXT PRIMARY KEY, evidence TEXT NOT NULL, note TEXT, by TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS suits(
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, objective TEXT, inputs TEXT, concepts TEXT, operations TEXT,
  views TEXT, acceptance TEXT, recipe TEXT, judgement TEXT, origin TEXT, proposal TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS suit_evaluations(
  id INTEGER PRIMARY KEY, suit_id INTEGER NOT NULL REFERENCES suits(id) ON DELETE CASCADE, eval_id TEXT NOT NULL, payload TEXT NOT NULL,
  sha256 TEXT, backing_at_import TEXT, imported REAL, UNIQUE(suit_id, eval_id));
CREATE TABLE IF NOT EXISTS gap_flags(
  gap_id INTEGER PRIMARY KEY REFERENCES gaps(id) ON DELETE CASCADE, status TEXT NOT NULL, capability_key TEXT, evidence TEXT, reason TEXT,
  matched TEXT, flagged REAL, updated REAL);
"""

#: SQL condition for the gaps that really are open: not resolved, and not flagged as possibly stale by the reconciliation.
OPEN_GAP_SQL = "state='abierta' AND id NOT IN (SELECT gap_id FROM gap_flags WHERE status='possibly_stale')"

_STATE_FIELDS = {
    ("proposals", "state"): PROPOSAL_STATES,
    ("deliveries", "implementation"): IMPLEMENTATION_STATES,
    ("deliveries", "verification"): VERIFICATION_STATES,
    ("deliveries", "relation"): RELATIONS,
    ("capabilities", "operation"): OPERATION_STATES,
    ("gaps", "state"): GAP_STATES,
}
GAP_FLAG_STATES = ("possibly_stale", "dismissed")


def _j(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for key in ("provenance", "declared", "meta", "evidence", "watch", "counts"):
        if isinstance(out.get(key), str) and out[key][:1] in "{[":
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    return out


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def q(self, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [_row(r) for r in self._conn.execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        with self._lock:
            return _row(self._conn.execute(sql, tuple(args)).fetchone())

    # ------------------------------------------------------------------ sources

    def upsert_source(self, *, url: str = "", repo: str = "", title: str = "", kind: str = "", summary: str = "",
                      license: str = "", stars: str = "", legacy_radar_no: Optional[int] = None, github_id: Optional[int] = None,
                      seen_at: Optional[float] = None, meta: Optional[dict] = None, key: str = "") -> int:
        """Create or enrich a source. Existing non-empty fields are kept; empty ones are filled. Returns its id."""
        repo = repo or (repo_of(url) or "")
        key = key or source_key(url=url, repo=repo, title=title)
        alias_id = self._alias(key)
        now = time.time()
        seen = seen_at or now
        kind = kind or ("repo" if key.startswith("repo:") else "idea" if key.startswith("idea:") else "article")
        url = f"https://github.com/{repo}" if repo and not url else (canonical_url(url) if url else "")
        with self.tx() as c:
            row = c.execute("SELECT * FROM sources WHERE key=? OR id=?", (key, alias_id or -1)).fetchone()
            if row is None and github_id:
                row = c.execute("SELECT * FROM sources WHERE github_id=?", (github_id,)).fetchone()
            if row is None:
                cur = c.execute(
                    "INSERT INTO sources(key, kind, url, repo, github_id, title, summary, license, stars, legacy_radar_no, first_seen, "
                    "last_seen, created, updated, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, kind, url, repo or None, github_id, title or repo or url, summary, license, stars, legacy_radar_no, seen, seen,
                     now, now, _j(meta or {})))
                return int(cur.lastrowid)
            sid = int(row["id"])
            fields = {"url": url, "repo": repo, "github_id": github_id, "title": title, "summary": summary, "license": license,
                      "stars": stars, "legacy_radar_no": legacy_radar_no}
            updates = {k: v for k, v in fields.items() if v not in (None, "") and row[k] in (None, "")}
            if row["key"] != key:
                c.execute("INSERT OR IGNORE INTO source_aliases(alias, source_id) VALUES (?,?)", (key, sid))
            first = min(row["first_seen"] or seen, seen)
            last = max(row["last_seen"] or seen, seen)
            updates.update(first_seen=first, last_seen=last, updated=now)
            if meta:
                merged = dict(json.loads(row["meta"] or "{}"))
                for k, v in meta.items():
                    merged.setdefault(k, v)
                updates["meta"] = _j(merged)
            sets = ", ".join(f"{k}=?" for k in updates)
            c.execute(f"UPDATE sources SET {sets} WHERE id=?", (*updates.values(), sid))
            return sid

    def recanonicalize(self) -> dict[str, int]:
        """Re-key URL sources after a change in ``canonical_url``: a source whose key changes is renamed, or merged into
        the source that already has the new key (its captures, ideas, proposals and deliveries move with it). The old key
        stays as an alias so lookups by it still land. Idempotent."""
        renamed = merged = 0
        for row in self.q("SELECT id, key, url FROM sources WHERE key LIKE 'url:%'"):
            new_url = canonical_url(row["key"][4:])
            new_key = source_key(url=new_url) if new_url else row["key"]
            if new_key == row["key"]:
                continue
            with self.tx() as c:
                target = c.execute("SELECT id FROM sources WHERE key=?", (new_key,)).fetchone()
                sid = int(row["id"])
                if target is None:
                    c.execute("UPDATE sources SET key=?, url=?, updated=? WHERE id=?", (new_key, new_url, time.time(), sid))
                    c.execute("INSERT OR IGNORE INTO source_aliases(alias, source_id) VALUES (?,?)", (row["key"], sid))
                    renamed += 1
                    continue
                tid = int(target["id"])
                for table in ("captures", "ideas", "proposals", "deliveries"):
                    c.execute(f"UPDATE {table} SET source_id=? WHERE source_id=?", (tid, sid))
                c.execute("INSERT OR IGNORE INTO capture_sources(capture_id, source_id) "
                          "SELECT capture_id, ? FROM capture_sources WHERE source_id=?", (tid, sid))
                c.execute("DELETE FROM capture_sources WHERE source_id=?", (sid,))
                c.execute("UPDATE OR IGNORE source_aliases SET source_id=? WHERE source_id=?", (tid, sid))
                c.execute("DELETE FROM source_aliases WHERE source_id=?", (sid,))
                c.execute("INSERT OR IGNORE INTO source_aliases(alias, source_id) VALUES (?,?)", (row["key"], tid))
                c.execute("UPDATE sources SET first_seen=MIN(first_seen, (SELECT first_seen FROM sources WHERE id=?)), "
                          "last_seen=MAX(last_seen, (SELECT last_seen FROM sources WHERE id=?)) WHERE id=?", (sid, sid, tid))
                c.execute("DELETE FROM sources WHERE id=?", (sid,))
                c.execute("UPDATE sources SET captures=(SELECT COUNT(*) FROM capture_sources WHERE source_id=?) WHERE id=?", (tid, tid))
                merged += 1
        return {"renamed": renamed, "merged": merged}

    def _alias(self, key: str) -> Optional[int]:
        row = self.one("SELECT source_id FROM source_aliases WHERE alias=?", (key,))
        return row["source_id"] if row else None

    def add_alias(self, source_id: int, alias: str) -> None:
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO source_aliases(alias, source_id) VALUES (?,?)", (alias, source_id))

    def source(self, source_id: int) -> Optional[dict[str, Any]]:
        return self.one("SELECT * FROM sources WHERE id=?", (source_id,))

    def source_by_key(self, key: str) -> Optional[dict[str, Any]]:
        row = self.one("SELECT * FROM sources WHERE key=?", (key,))
        if row is None:
            alias = self._alias(key)
            row = self.source(alias) if alias else None
        return row

    # ------------------------------------------------------------------ captures

    def add_capture(self, *, capture_key: str, channel: str, text: str = "", url: str = "", at: Optional[float] = None,
                    author: str = "", chat: str = "", attachment: str = "", provenance: Optional[dict] = None,
                    declared: Optional[dict] = None, source_id: Optional[int] = None) -> tuple[int, bool]:
        """Store one appearance of something. Idempotent on ``capture_key`` (returns ``(id, created)``): importing the
        same document or chat twice never duplicates a capture."""
        now = time.time()
        with self.tx() as c:
            row = c.execute("SELECT id, source_id FROM captures WHERE capture_key=?", (capture_key,)).fetchone()
            if row is not None:
                if source_id and not row["source_id"]:
                    c.execute("UPDATE captures SET source_id=? WHERE id=?", (source_id, row["id"]))
                return int(row["id"]), False
            cur = c.execute(
                "INSERT INTO captures(capture_key, channel, source_id, at, author, chat, text, url, attachment, provenance, declared, created) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (capture_key, channel, source_id, at or now, author, chat, text, url, attachment, _j(provenance or {}), _j(declared or {}), now))
            cid = int(cur.lastrowid)
            if source_id:
                c.execute("INSERT OR IGNORE INTO capture_sources(capture_id, source_id) VALUES (?,?)", (cid, source_id))
                c.execute("UPDATE sources SET captures=captures+1 WHERE id=?", (source_id,))
            return cid, True

    def set_capture_declared(self, capture_id: int, key: str, value: Any) -> None:
        """Add one derived field (e.g. ``ocr``) to a capture's ``declared`` JSON without touching the rest."""
        with self.tx() as c:
            row = c.execute("SELECT declared FROM captures WHERE id=?", (capture_id,)).fetchone()
            if row is None:
                return
            data = json.loads(row["declared"] or "{}")
            data[key] = value
            c.execute("UPDATE captures SET declared=? WHERE id=?", (_j(data), capture_id))

    def link_capture(self, capture_id: int, source_id: int) -> None:
        with self.tx() as c:
            cur = c.execute("INSERT OR IGNORE INTO capture_sources(capture_id, source_id) VALUES (?,?)", (capture_id, source_id))
            if cur.rowcount:
                c.execute("UPDATE sources SET captures=captures+1 WHERE id=?", (source_id,))
            c.execute("UPDATE captures SET source_id=COALESCE(source_id, ?) WHERE id=?", (source_id, capture_id))

    # ------------------------------------------------------------------ ideas, proposals, deliveries

    def upsert_idea(self, *, key: str, source_id: Optional[int], title: str, benefit: str = "") -> int:
        now = time.time()
        with self.tx() as c:
            row = c.execute("SELECT id FROM ideas WHERE key=?", (key,)).fetchone()
            if row:
                return int(row["id"])
            return int(c.execute("INSERT INTO ideas(key, source_id, title, benefit, created, updated) VALUES (?,?,?,?,?,?)",
                                 (key, source_id, title, benefit, now, now)).lastrowid)

    def upsert_proposal(self, *, key: str, source_id: Optional[int], target: str = "", state: str = "pendiente", reason: str = "",
                        origin: str = "", idea_id: Optional[int] = None, capability_key: str = "", agora_space: str = "",
                        agora_task: Optional[int] = None, agora_thread: Optional[int] = None, declared: Optional[dict] = None,
                        by: str = "import") -> int:
        """Create a proposal, or fill the blanks of an existing one. A *different* state for an existing proposal goes
        through :meth:`set_state` (history) and only when ``origin`` ranks at least as high as the stored one."""
        if state not in PROPOSAL_STATES:
            raise ValueError(f"Unknown proposal state: {state}")
        now = time.time()
        with self.tx() as c:
            row = c.execute("SELECT * FROM proposals WHERE key=?", (key,)).fetchone()
            if row is None:
                return int(c.execute(
                    "INSERT INTO proposals(key, source_id, idea_id, target, capability_key, state, reason, origin, agora_space, agora_task, "
                    "agora_thread, declared, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, source_id, idea_id, target or None, capability_key or None, state, reason, origin, agora_space or None, agora_task,
                     agora_thread, _j(declared or {}), now, now)).lastrowid)
            pid = int(row["id"])
            fields = {"idea_id": idea_id, "target": target, "capability_key": capability_key, "reason": reason,
                      "agora_space": agora_space, "agora_task": agora_task, "agora_thread": agora_thread}
            updates = {k: v for k, v in fields.items() if v not in (None, "") and row[k] in (None, "")}
            if declared:
                merged = dict(json.loads(row["declared"] or "{}"))
                merged.update({k: v for k, v in declared.items() if k not in merged})
                updates["declared"] = _j(merged)
            if updates:
                updates["updated"] = now
                c.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), pid))
        if row["state"] != state and _rank(origin) >= _rank(row["origin"] or ""):
            self.set_state("proposals", pid, "state", state, by=by, note=origin)
            with self.tx() as c:
                c.execute("UPDATE proposals SET origin=? WHERE id=?", (origin, pid))
        return pid

    def upsert_delivery(self, *, key: str, source_id: Optional[int], target: str, proposal_id: Optional[int] = None, repo: str = "",
                        commit_sha: str = "", relation: str = "desconocida", implementation: str = "sin_implementar",
                        verification: str = "desconocida", capability_key: str = "", evidence: Optional[dict] = None,
                        agora_space: str = "", agora_task: Optional[int] = None, declared: Optional[dict] = None, by: str = "import") -> int:
        for field, value in (("relation", relation), ("implementation", implementation), ("verification", verification)):
            if value not in _STATE_FIELDS[("deliveries", field)]:
                raise ValueError(f"Unknown {field}: {value}")
        now = time.time()
        with self.tx() as c:
            row = c.execute("SELECT * FROM deliveries WHERE key=?", (key,)).fetchone()
            if row is None:
                return int(c.execute(
                    "INSERT INTO deliveries(key, proposal_id, source_id, target, capability_key, repo, commit_sha, relation, implementation, "
                    "verification, evidence, agora_space, agora_task, declared, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, proposal_id, source_id, target, capability_key or None, repo or None, commit_sha or None, relation, implementation,
                     verification, _j(evidence or {}), agora_space or None, agora_task, _j(declared or {}), now, now)).lastrowid)
            did = int(row["id"])
            fields = {"proposal_id": proposal_id, "capability_key": capability_key, "repo": repo, "commit_sha": commit_sha,
                      "agora_space": agora_space, "agora_task": agora_task}
            updates = {k: v for k, v in fields.items() if v not in (None, "") and row[k] in (None, "")}
            if updates:
                updates["updated"] = now
                c.execute(f"UPDATE deliveries SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), did))
        return did

    def set_state(self, entity: str, entity_id: int, field: str, value: str, *, by: str = "", note: str = "") -> bool:
        """Change one state field, writing the old value to ``history``. Returns False when nothing changed."""
        allowed = _STATE_FIELDS.get((entity, field))
        if allowed is None:
            raise ValueError(f"{entity}.{field} is not a state field")
        if value not in allowed:
            raise ValueError(f"{entity}.{field} must be one of: {', '.join(allowed)}")
        now = time.time()
        with self.tx() as c:
            row = c.execute(f"SELECT {field} FROM {entity} WHERE id=?", (entity_id,)).fetchone()
            if row is None:
                raise KeyError(f"{entity} {entity_id} does not exist")
            old = row[0]
            if old == value:
                return False
            c.execute(f"UPDATE {entity} SET {field}=?, updated=? WHERE id=?" if entity != "capabilities"
                      else f"UPDATE {entity} SET {field}=?, seen=? WHERE id=?", (value, now, entity_id))
            c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES (?,?,?,?,?,?,?,?)",
                      (entity, entity_id, field, old, value, now, by, note))
        return True

    # ------------------------------------------------------------------ gaps, imports, meta

    def add_gap(self, *, title: str, detail: str = "", target: str = "", capability_key: str = "", watch: Optional[dict] = None) -> int:
        now = time.time()
        with self.tx() as c:
            return int(c.execute("INSERT INTO gaps(title, detail, target, capability_key, watch, created, updated) VALUES (?,?,?,?,?,?,?)",
                                 (title, detail, target or None, capability_key or None, _j(watch), now, now)).lastrowid)

    def record_import(self, *, name: str, file: str, sha256: str, counts: dict) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO imports(name, file, sha256, at, counts) VALUES (?,?,?,?,?)", (name, file, sha256, time.time(), _j(counts)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _j(value)))

    # ------------------------------------------------------------------ reading

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("sources", "captures", "ideas", "proposals", "deliveries", "capabilities", "gaps"):
            out[table] = self.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        return out

    def history_of(self, entity: str, entity_id: int) -> list[dict[str, Any]]:
        return self.q("SELECT * FROM history WHERE entity=? AND entity_id=? ORDER BY at", (entity, entity_id))


#: Who may override a proposal state set by whom: a person or the Ágora outranks a document; a document outranks a guess.
_ORIGIN_RANK = {"": 0, "mention": 1, "guide": 2, "radar": 2, "radar-ideas": 2, "tracker": 3, "agora": 4, "agent": 4, "luis": 5}


def _rank(origin: str) -> int:
    return _ORIGIN_RANK.get((origin or "").split(":", 1)[0], 1)
