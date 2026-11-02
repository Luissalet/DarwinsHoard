"""Import the radar history that lived in Markdown files and in the Ágora, keeping every line's provenance.

Sources (all optional; whatever exists is read):

* ``RADAR_GITTREND.md``      numbered entries ``N. **[owner/repo](url)** · ⭐ … · LABEL — text``
* ``radar-ideas.md``         entries 426-510 exported from Claude's project (``- **#N** **[title](url)** · …``)
* ``IMPLEMENTACION_RADAR.md`` the tracker table ``| N | repo | estado | qué | commits |`` (Faustus implementations)
* ``GUIA_IMPLEMENTACION.md``  the guide checklist ``- [x|~| ] **NNN** [repo](url) · tipo · …``
* the Ágora (``GET <hub>/api/agora/tasks``): tasks that cite ``radar #N`` become proposals for their space's app

What a document *declares* is stored as declared (``captures.declared``, ``proposals.declared``) and mapped to a proposal
state with an ``origin`` that ranks how much it can be trusted (see ``store._ORIGIN_RANK``). A delivery taken from the
tracker is ``implementation=integrada`` / ``verification=documentada``: the tracker *says* it was done; whether the commit
is in the main branch today is checked elsewhere (``darwin_ingest`` ancestry). Nothing here invents a state.

Every capture key is the channel, the radar number and a hash of the line, so importing the same file twice adds
nothing, and an edited line becomes a second appearance instead of overwriting the first."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .canon import canonical_url, repo_of, source_key
from .store import Store

URL_RE = re.compile(r"https?://[^\s)\]>»]+")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
STARS_RE = re.compile(r"⭐\s*([~<>]?\s*[\d.,]+\s*[kKmM]?|—|-)")
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
TASK_RE = re.compile(r"(?:tareas?|Ágora|agora|task)\s*\*{0,2}#(\d{2,5})\*{0,2}|\(#(\d{4,5})\)", re.I)
RADAR_REF_RE = re.compile(r"radar\s*#?\s*(\d{1,3})\b|\(radar\s+#(\d{1,3})\)", re.I)

LABELS = [  # (pattern, label) - first match wins
    (r"\bdecisi[oó]n de Luis\b", "decision-luis"),
    (r"\bfuera de tema\b", "off-topic"),
    (r"\bSKIP\b", "skip"),
    (r"\bCOVERED\b", "covered"),
    (r"\bPARTIAL\b", "partial"),
    (r"\bNEW\b", "new"),
    (r"\bIMPLEMENT\b", "implement"),
    (r"\breferencia\b", "reference"),
    (r"\bdescartad[oa]\b", "discarded"),
]
LABEL_STATE = {"skip": "descartada", "off-topic": "descartada", "discarded": "descartada", "covered": "cubierta",
               "partial": "pendiente", "new": "pendiente", "implement": "aceptada", "reference": "pendiente",
               "decision-luis": "pendiente", "": "pendiente"}

#: Words in the documents that name a family app, mapped to the app id the hub uses. Absorbed apps keep their own id
#: (the hub lists them as aliases of the host): the tree shows where they live today.
APP_WORDS = {
    "faustus": "faustus", "hub": "hoardhub", "hoard hub": "hoardhub", "hoard link": "hoardhub", "hoardlink": "hoardhub",
    "ágora": "hoardhub", "agora": "hoardhub", "atlas": "atlas", "baird": "baird", "cicero": "cicero", "coase": "coase",
    "midas": "midas", "cook": "cookhoard", "cookhoard": "cookhoard", "daguerre": "daguerre", "dürer": "daguerre",
    "dorian": "dorian", "gamer": "gamerhoard", "gamerhoard": "gamerhoard", "hermes": "hermes", "tantalus": "tantalus",
    "phileas": "phileas", "home hoard": "homehoard", "homehoard": "homehoard", "hypatia": "hypatia", "jobhunter": "jobhunter",
    "kafka": "kafka", "kinect": "kinect-hoard", "ledger": "ledger", "links": "links", "mercator": "mercator",
    "nightingale": "nightingale", "laplace": "laplace", "people": "people", "prometheus": "prometheus", "prospero": "prospero",
    "lumiere": "lumiere", "pygmalion": "pygmalion", "galton": "galton", "silver": "silver", "talos": "talos", "argus": "argus",
    "cassandra": "cassandra", "diskhoard": "diskhoard", "echo": "echo", "funes": "funes", "vitruvius": "vitruvius",
    "babel": "babel", "theseus": "theseus", "vulcan": "vulcan", "gepetto": "gepetto", "plato": "platos", "gulliver": "gulliver",
    "writer": "writer", "writers": "writer", "scheherazade": "scheherazade", "borges": "borges", "scribe": "scribe",
    "hoard dex": "hoarddex", "hoarddex": "hoarddex", "fielddex": "hoarddex", "hoard grab": "hoard-grab", "watchhoard": "watchhoard",
    "jarvis": "faustus", "cookbook": "faustus",
}
_APP_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(w) for w in APP_WORDS), key=len, reverse=True)) + r")(?:'s)?\b", re.I)

SPACE_APP = {"hoardlink": "hoardhub", "writers": "writer", "kinect": "kinect-hoard", "ecosystem": "", "research": "",
             "codehelper": "", "vertico": "", "fisiones": "", "darwin": "darwin"}


def app_mentions(text: str) -> list[str]:
    seen: list[str] = []
    for m in _APP_RE.finditer(text or ""):
        app = APP_WORDS[m.group(1).lower()]
        if app not in seen:
            seen.append(app)
    return seen


def _label(text: str) -> str:
    for pattern, label in LABELS:
        if re.search(pattern, text):
            return label
    return ""


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


@dataclass
class Entry:
    number: int
    line: str
    lineno: int
    url: str = ""
    repo: str = ""
    title: str = ""
    stars: str = ""
    label: str = ""
    pinned: bool = False
    description: str = ""
    targets: list[str] = field(default_factory=list)
    tasks: list[int] = field(default_factory=list)


def parse_radar_line(line: str, lineno: int, number: int) -> Entry:
    """One radar entry (either file format). Tolerant: whatever is not recognised stays in ``description``."""
    body = line
    link = MD_LINK_RE.search(body)
    url = link.group(2) if link else (URL_RE.search(body).group(0) if URL_RE.search(body) else "")
    title = link.group(1) if link else ""
    if not title:
        bold = re.search(r"\*\*([^*]+)\*\*", re.sub(r"^\s*(?:-\s*)?\*\*#?\d+\*\*\s*", "", body))
        title = bold.group(1).strip() if bold else ""
    repo = repo_of(url) if url else (repo_of(title) or "")
    stars_m = STARS_RE.search(body)
    stars = stars_m.group(1).strip() if stars_m and stars_m.group(1) not in ("—", "-") else ""
    desc = body.split(" — ", 1)[1].strip() if " — " in body else ""
    tasks = sorted({int(a or b) for a, b in TASK_RE.findall(body)})
    how = desc.split("**Cómo", 1)[1] if "**Cómo" in desc else (desc.split("Destino:", 1)[1] if "Destino:" in desc else "")
    targets = app_mentions(how)
    return Entry(number=number, line=line, lineno=lineno, url=url, repo=repo or "", title=title, stars=stars,
                 label=_label(body), pinned="📌" in body, description=desc[:2000], targets=targets, tasks=tasks)


@dataclass
class ImportReport:
    name: str
    file: str = ""
    sha256: str = ""
    entries: int = 0
    new_captures: int = 0
    sources: int = 0
    proposals: int = 0
    deliveries: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "skipped"} | {"skipped": self.skipped[:50],
                                                                               "skipped_count": len(self.skipped)}


class LegacyImporter:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------------ helpers

    def _source_for(self, e: Entry) -> int:
        kind = "repo" if e.repo else ("paper" if "arxiv.org" in e.url else "article" if e.url else "idea")
        meta = {"pinned": True} if e.pinned else None
        return self.store.upsert_source(url=e.url, repo=e.repo, title=e.title or e.repo or e.url, kind=kind, stars=e.stars,
                                        legacy_radar_no=e.number, summary=e.description[:600], meta=meta,
                                        key=source_key(url=e.url, repo=e.repo, title=e.title or f"radar {e.number}"))

    def _capture(self, channel: str, e: Entry, file: str, file_sha: str, sid: int, declared: dict) -> bool:
        key = f"{channel}:{e.number}:{_sha(e.line.strip())[:20]}"
        _, created = self.store.add_capture(capture_key=key, channel=channel, text=e.line.strip(), url=canonical_url(e.url) if e.url else "",
                                            provenance={"file": file, "line": e.lineno, "file_sha256": file_sha, "radar_no": e.number},
                                            declared=declared, source_id=sid, author="luis" if e.pinned else "radar")
        return created

    def _proposal(self, sid: int, target: str, state: str, origin: str, *, reason: str = "", declared: Optional[dict] = None,
                  agora_space: str = "", agora_task: Optional[int] = None) -> int:
        src = self.store.source(sid)
        return self.store.upsert_proposal(key=f"{src['key']}->{target or '?'}", source_id=sid, target=target, state=state, origin=origin,
                                          reason=reason, declared=declared, agora_space=agora_space, agora_task=agora_task)

    # ------------------------------------------------------------------ radar files

    def import_radar(self, path: Path, *, channel: str = "radar") -> ImportReport:
        raw = path.read_bytes()
        rep = ImportReport(name=channel, file=str(path), sha256=_sha(raw))
        text = raw.decode("utf-8-sig", errors="replace")
        pattern = re.compile(r"^\s*(\d{1,4})\.\s+\S") if channel == "radar" else re.compile(r"^\s*-\s*\*\*#(\d{1,4})\*\*")
        sources: set[int] = set()
        for lineno, line in enumerate(text.splitlines(), 1):
            m = pattern.match(line)
            if not m:
                continue
            rep.entries += 1
            e = parse_radar_line(line, lineno, int(m.group(1)))
            if not (e.url or e.title):
                rep.skipped.append(f"{path.name}:{lineno} sin enlace ni título")
                continue
            sid = self._source_for(e)
            sources.add(sid)
            declared = {"label": e.label, "stars": e.stars, "pinned": e.pinned, "targets": e.targets, "tasks": e.tasks}
            if self._capture(channel, e, str(path), rep.sha256, sid, declared):
                rep.new_captures += 1
            state = LABEL_STATE.get(e.label, "pendiente")
            targets = e.targets or [""]
            for target in targets:
                self._proposal(sid, target, state, channel, reason=e.label, declared={"radar_label": e.label})
                rep.proposals += 1
        rep.sources = len(sources)
        self.store.record_import(name=channel, file=str(path), sha256=rep.sha256, counts=rep.as_dict())
        return rep

    # ------------------------------------------------------------------ tracker table

    @staticmethod
    def tracker_state(status: str) -> tuple[str, str]:
        """(proposal state, implementation declared) from the tracker's «Estado» cell."""
        s = status.strip().lower()
        if s.startswith("✅"):
            return "aceptada", "integrada"
        if s.startswith("⏸"):
            return "aplazada", "parcial"
        if s.startswith("❌") or "descartad" in s:
            return "descartada", ""
        if s.startswith("➖"):
            return ("cubierta", "") if ("cubiert" in s or "se une" in s or "ya " in s) else ("descartada", "")
        if s.startswith("⏭"):
            return "aplazada", ""
        if s.startswith("⏳"):
            return "investigando", ""
        return "pendiente", ""

    def import_tracker(self, path: Path) -> ImportReport:
        raw = path.read_bytes()
        rep = ImportReport(name="tracker", file=str(path), sha256=_sha(raw))
        sources: set[int] = set()
        for lineno, line in enumerate(raw.decode("utf-8-sig", errors="replace").splitlines(), 1):
            m = re.match(r"^\|\s*(\d{1,4})\s*\|", line)
            if not m:
                continue
            rep.entries += 1
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                rep.skipped.append(f"{path.name}:{lineno} fila corta")
                continue
            number = int(cells[0])
            repo_cell, status, what = cells[1], cells[2], cells[3]
            commits_cell = cells[4] if len(cells) > 4 else ""
            link = MD_LINK_RE.search(repo_cell)
            url = link.group(2) if link else ""
            repo = repo_of(url) if url else (repo_of(repo_cell.strip("`* ")) or "")
            existing = self.store.one("SELECT id FROM sources WHERE legacy_radar_no=? ORDER BY id LIMIT 1", (number,))
            if existing and not (repo or url):
                sid = existing["id"]
            else:
                if not (repo or url or repo_cell):
                    rep.skipped.append(f"{path.name}:{lineno} sin repo")
                    continue
                sid = self.store.upsert_source(url=url, repo=repo, title=(link.group(1) if link else repo_cell.strip("`* ")),
                                               legacy_radar_no=number,
                                               key=source_key(url=url, repo=repo, title=repo_cell or f"radar {number}"))
            sources.add(sid)
            state, impl = self.tracker_state(status)
            commits = SHA_RE.findall(commits_cell) + [c for c in SHA_RE.findall(status) if c not in commits_cell]
            declared = {"status": status, "what": what[:1500], "commits": commits}
            e = Entry(number=number, line=line, lineno=lineno)
            if self._capture("tracker", e, str(path), rep.sha256, sid, declared):
                rep.new_captures += 1
            target = "faustus"
            hoards = [a for a in app_mentions(status) if a != "faustus"]
            if "hoard" in status.lower() and hoards:
                target = hoards[0]
            pid = self._proposal(sid, target, state, "tracker", reason=status, declared={"tracker_status": status})
            rep.proposals += 1
            if impl:
                src = self.store.source(sid)
                for sha in commits or [""]:
                    self.store.upsert_delivery(key=f"{src['key']}->{target}@{sha or 'sin-commit'}", source_id=sid, target=target,
                                               proposal_id=pid, repo="Faustus" if target == "faustus" else "", commit_sha=sha,
                                               implementation=impl, verification="documentada",
                                               declared={"tracker_status": status, "what": what[:600], "line": lineno})
                    rep.deliveries += 1
        rep.sources = len(sources)
        self.store.record_import(name="tracker", file=str(path), sha256=rep.sha256, counts=rep.as_dict())
        return rep

    # ------------------------------------------------------------------ guide checklist

    def import_guide(self, path: Path) -> ImportReport:
        raw = path.read_bytes()
        rep = ImportReport(name="guide", file=str(path), sha256=_sha(raw))
        sources: set[int] = set()
        for lineno, line in enumerate(raw.decode("utf-8-sig", errors="replace").splitlines(), 1):
            m = re.match(r"^- \[([ x~])\] \*\*(\d{1,4})\*\*", line)
            if not m:
                continue
            rep.entries += 1
            box, number = m.group(1), int(m.group(2))
            e = parse_radar_line(line, lineno, number)
            parts = [p.strip() for p in line.split(" · ")]
            kind = parts[1] if len(parts) > 2 else ""
            if not (e.url or e.repo):
                rep.skipped.append(f"{path.name}:{lineno} sin repo")
                continue
            sid = self._source_for(e)
            sources.add(sid)
            if self._capture("guide", e, str(path), rep.sha256, sid, {"checkbox": box, "kind": kind}):
                rep.new_captures += 1
            state = {"x": "aceptada", "~": "descartada", " ": "pendiente"}[box]
            # The guide was about Faustus (and its Hoards through connectors); its checkbox speaks for Faustus.
            self._proposal(sid, "faustus", state, "guide", reason=f"guía [{box}] {kind}".strip(), declared={"guide_checkbox": box})
            rep.proposals += 1
        rep.sources = len(sources)
        self.store.record_import(name="guide", file=str(path), sha256=rep.sha256, counts=rep.as_dict())
        return rep

    # ------------------------------------------------------------------ Ágora

    def import_agora(self, hub_url: str, *, timeout: float = 15.0, spaces: Optional[Iterable[str]] = None) -> ImportReport:
        """Tasks that cite ``radar #N`` (title or body) become proposals for their space's app, with the task linked.
        Task status maps to the proposal state; a ``done`` task with commits adds a declared delivery."""
        rep = ImportReport(name="agora", file=hub_url)

        def get(path: str) -> Any:
            with urllib.request.urlopen(hub_url.rstrip("/") + path, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))

        if spaces is None:
            spaces = [s["id"] for s in get("/api/agora/spaces").get("spaces", [])]
        status_state = {"open": "aceptada", "claimed": "investigando", "in_progress": "investigando", "review": "investigando",
                        "approved": "aceptada", "changes": "investigando", "done": "aceptada", "dropped": "descartada",
                        "blocked": "aplazada", "waiting": "aplazada"}
        seen: set[int] = set()
        for space in spaces:
            tasks: list[dict[str, Any]] = []
            cursor: Optional[str] = "0"
            try:
                while cursor is not None and len(tasks) < 20000:
                    page = get(f"/api/agora/tasks?space_id={space}&limit=500&cursor={cursor}")
                    tasks.extend(page.get("tasks", []))
                    cursor = page.get("next_cursor")
            except Exception as exc:  # noqa: BLE001 - one space failing must not stop the rest
                rep.skipped.append(f"{space}: {exc}")
                if not tasks:
                    continue
            for t in tasks:
                if t.get("id") in seen or (t.get("space_id") or space) != space:
                    continue
                seen.add(t["id"])
                text = f"{t.get('title', '')}\n{t.get('body', '')}"
                numbers = sorted({int(a or b) for a, b in RADAR_REF_RE.findall(text)})
                labels = [l for l in (t.get("labels") or []) if str(l).startswith("darwin:")]
                if not numbers and not labels:
                    continue
                rep.entries += 1
                target = SPACE_APP.get(space, space)
                state = status_state.get(t.get("status", ""), "pendiente")
                for number in numbers:
                    src = self.store.one("SELECT id, key FROM sources WHERE legacy_radar_no=? ORDER BY id LIMIT 1", (number,))
                    if not src:
                        rep.skipped.append(f"tarea {t['id']}: radar #{number} sin fuente importada")
                        continue
                    tgt = target or (app_mentions(text)[:1] or [""])[0]
                    key = f"agora:{space}:{t['id']}:{number}"
                    _, created = self.store.add_capture(capture_key=key, channel="agora", text=t.get("title", ""), at=t.get("created"),
                                                        author=t.get("created_by", ""), chat=space, source_id=src["id"],
                                                        provenance={"space": space, "task": t["id"], "thread": t.get("thread_id")},
                                                        declared={"status": t.get("status"), "owner": t.get("owner"),
                                                                  "commits": t.get("commits") or []})
                    rep.new_captures += int(created)
                    pid = self._proposal(src["id"], tgt, state, "agora", reason=f"tarea {space}#{t['id']} {t.get('status')}",
                                         agora_space=space, agora_task=t["id"])
                    rep.proposals += 1
                    if t.get("status") == "done" and t.get("commits"):
                        repo = t.get("repo") or space
                        for sha in t["commits"]:
                            did = self.store.upsert_delivery(key=f"{src['key']}->{tgt}@{sha}", source_id=src["id"], target=tgt, proposal_id=pid,
                                                       repo=repo, commit_sha=str(sha), implementation="integrada", verification="documentada",
                                                       agora_space=space, agora_task=t["id"],
                                                       declared={"agora_status": "done", "title": t.get("title", "")[:300]})
                            with self.store.tx() as c:  # the task names the repository; it outranks the space guess
                                c.execute("UPDATE deliveries SET repo=? WHERE id=? AND COALESCE(repo,'')<>?", (repo, did, repo))
                            rep.deliveries += 1
        self.store.record_import(name="agora", file=hub_url, sha256="", counts=rep.as_dict())
        return rep

    # ------------------------------------------------------------------ all at once

    def import_all(self, *, inspiration_dir: Path, radar_ideas: Optional[Path] = None, hub_url: str = "",
                   agora: bool = True, hoards_root: Optional[Path] = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        files = [("radar", inspiration_dir / "RADAR_GITTREND.md", self.import_radar),
                 ("radar-ideas", radar_ideas, lambda p: self.import_radar(p, channel="radar-ideas")),
                 ("tracker", inspiration_dir / "IMPLEMENTACION_RADAR.md", self.import_tracker),
                 ("guide", inspiration_dir / "GUIA_IMPLEMENTACION.md", self.import_guide)]
        for name, path, fn in files:
            if path and Path(path).is_file():
                out[name] = fn(Path(path)).as_dict()
            else:
                out[name] = {"missing": str(path)}
        if agora and hub_url:
            try:
                out["agora"] = self.import_agora(hub_url).as_dict()
            except Exception as exc:  # noqa: BLE001
                out["agora"] = {"error": str(exc)}
        if hoards_root:
            from .gaps import import_objectives
            try:
                out["objetivos"] = import_objectives(self.store, Path(hoards_root))
            except Exception as exc:  # noqa: BLE001
                out["objetivos"] = {"error": str(exc)}
        out["counts"] = self.store.counts()
        # Numbers come from the captures, not the sources: several radar entries can be the same source (two entries
        # pointing at the same releases page), and each must still count as present.
        numbers = {int(r["n"]) for r in self.store.q("SELECT DISTINCT json_extract(provenance, '$.radar_no') AS n FROM captures "
                                                     "WHERE json_extract(provenance, '$.radar_no') IS NOT NULL")}
        top = max(numbers) if numbers else 0
        out["radar_numbers"] = {"distinct": len(numbers), "max": top, "missing": [n for n in range(1, top + 1) if n not in numbers]}
        self.store.set_meta("radar_missing", out["radar_numbers"]["missing"])
        return out
