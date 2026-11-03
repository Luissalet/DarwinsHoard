"""The capability tree of the family: Faustus (root) > Hoard Hub > Hoards > absorbed modules > capabilities > tools.

Built from the authorities, never typed by hand:

* the hub's ``GET /api/apps``: every app, its state, its declared capabilities and who absorbed it (``family.absorbed_by``);
* Faustus's ``GET /api/tools/catalog`` + ``/api/tools/footprint``: the tools Faustus really sees, native and per MCP
  server (the *live* layer: ``evidence=viva``);
* the ``faustus-plugin.json`` manifests under the Hoards folders, when the hub is not answering (``evidence=declarada``).

A refresh upserts nodes (``since`` = first time seen, ``seen`` = last time). Nodes that stop appearing are kept with
their old ``seen``: the tree remembers what existed. Apps that are down stay in the tree as ``detenida``: an app being
stopped does not mean its capability is gone.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .backing import all_backing, is_backed
from .store import Store, _j

ROOT = "faustus"
HUB = "hoardhub"
STATE_OPERATION = {"running": "disponible", "down": "detenida", "stopped": "detenida", "foreign": "desconocida", "starting": "disponible"}

#: Spanish words people use when asking, mapped to the English tokens the manifests use (same idea as the hub's ALIASES).
ALIASES = {
    "voz": "voice speech tts audio", "imagen": "image photo", "foto": "photo image", "fotos": "photo image", "video": "video",
    "diseno": "design", "documento": "document paperwork pdf", "documentos": "document paperwork pdf", "3d": "3d mesh stl model",
    "agenda": "agenda calendar deadline reminder", "dinero": "finance budget accounts ledger", "cocina": "recipe cooking pantry",
    "pantalla": "screen screenshot", "capturas": "screenshot screen", "portapapeles": "clipboard", "codigo": "code coding api",
    "estudio": "study quiz exam", "contactos": "people contacts", "correo": "mail email", "envios": "shipment parcel",
    "precios": "price", "busqueda": "search", "buscar": "search", "reunion": "meeting minutes", "reuniones": "meeting minutes",
    "traducir": "translate", "modelos": "model", "juego": "game", "juegos": "game games", "mapa": "map terrain", "mapas": "map terrain",
    "musica": "music", "libros": "library books", "ocr": "ocr", "transcripcion": "transcription speech",
    "transcribir": "transcription speech", "grabar": "recording", "audio": "audio sound", "resumen": "summary digest",
    "repos": "repository git", "git": "git repository commits", "agentes": "agent agents", "navegador": "browser",
    "agente": "agent", "programar": "coding code", "programacion": "coding code", "memoria": "memory", "escribir": "writing",
    "escritura": "writing", "presentaciones": "slides presentation", "diapositivas": "slides", "datos": "data", "tablas": "table data",
    "graficos": "chart", "voces": "voice tts", "imagenes": "image", "modelo": "model", "local": "local", "web": "web",
}


STOPWORDS = {"donde", "hacemos", "hace", "hacen", "que", "quien", "quienes", "cual", "tenemos", "tiene", "ya", "como", "para", "por",
             "el", "la", "los", "las", "de", "del", "un", "una", "algo", "y", "o", "en", "con", "se", "puede", "podemos", "hay", "app",
             "apps", "hoard", "hoards", "the", "a", "an", "of", "to", "do", "does", "which", "who", "where"}


def folded(value: Any) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower()) if not unicodedata.combining(c))


#: A negation cue (English or Spanish) followed by a space: «does not», «doesn't», «never», «without», «no», «sin», «nunca», «ni».
#: «not only» / «no solo» / «not just» are not negations, nor is «no-code» (no space after the cue) or a condition
#: («if not», «si no», «cuando no»: what the tool does otherwise is still what it does).
_NEGATION_CUE = re.compile(r"(?<!\bif )(?<!\bsi )(?<!\bwhen )(?<!\bcuando )(?<!\bunless )"
                           r"\b(?:(?:does|do|did|is|are|was|were|has|have|had|can|could|will|would|should|wo|ca)n't|cannot|never|not|"
                           r"without|no|sin|nunca|ni|tampoco)\s+(?!(?:only|just|merely|solo|solamente|unicamente)\b)")
#: Where the negated stretch ends: the end of the sentence or clause, or a contrast word («but», «instead», «pero», «sino»).
_NEGATION_END = re.compile(r"[.;:!?\n()\[\]]|\b(?:but|instead|rather|although|however|pero|sino|aunque|en cambio)\b")


def affirmed(text: str) -> str:
    """``text`` without the stretches it denies, so «Does not perform OCR, transcription or model inference.» does not
    make its tool an OCR provider. Deterministic: a negation cue removes everything up to the end of its sentence or
    clause (or a contrast word); the rest of the text is kept as is."""
    text = str(text or "").replace("’", "'")
    out, pos = [], 0
    while True:
        m = _NEGATION_CUE.search(text, pos)
        if not m:
            out.append(text[pos:])
            return " ".join(part for part in out if part)
        out.append(text[pos:m.start()])
        end = _NEGATION_END.search(text, m.end())
        pos = end.start() if end else len(text)


def _get(url: str, timeout: float = 15.0, headers: Optional[dict] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class TreeBuilder:
    def __init__(self, store: Store, *, hub_url: str, faustus_url: str = "http://127.0.0.1:7000", hoards_root: Optional[Path] = None):
        self.store = store
        self.hub_url = hub_url.rstrip("/")
        self.faustus_url = faustus_url.rstrip("/")
        self.hoards_root = hoards_root
        self._nodes: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ collecting

    def _node(self, key: str, parent: Optional[str], level: str, name: str, *, app_id: str = "", detail: str = "",
              evidence: str = "declarada", operation: str = "desconocida", meta: Optional[dict] = None) -> None:
        prev = self._nodes.get(key)
        if prev:  # the same capability reached twice: keep the stronger evidence
            if _EVIDENCE_RANK[evidence] > _EVIDENCE_RANK[prev["evidence"]]:
                prev["evidence"] = evidence
            return
        self._nodes[key] = {"key": key, "parent_key": parent, "level": level, "name": name, "app_id": app_id, "detail": detail,
                            "evidence": evidence, "operation": operation, "meta": meta or {}}

    def collect(self) -> dict[str, Any]:
        report: dict[str, Any] = {"hub": None, "faustus": None, "manifests": None}
        self._node(ROOT, None, "root", "Faustus", app_id="faustus", detail="Estación de trabajo de IA: chat, agentes, proyectos, "
                   "investigación y conectores. Raíz del árbol.", evidence="declarada")
        self._node(HUB, ROOT, "hub", "Hoard Hub", app_id=HUB, detail="Corazón de la familia: lanza, vigila y conecta los Hoards; aloja el Ágora.")
        apps: list[dict[str, Any]] = []
        try:
            apps = _get(f"{self.hub_url}/api/apps").get("apps", [])
            report["hub"] = {"ok": True, "apps": len(apps)}
        except Exception as exc:  # noqa: BLE001 - the hub may be down; manifests are the fallback
            report["hub"] = {"ok": False, "error": str(exc)[:200]}
        if apps:
            self._from_hub(apps)
        else:
            report["manifests"] = self._from_manifests()
        report["faustus"] = self._from_faustus(apps)
        return report

    def _from_hub(self, apps: list[dict[str, Any]]) -> None:
        by_id = {a["id"]: a for a in apps}
        for a in apps:
            aid = a["id"]
            if aid == HUB:
                node_key, parent, level = HUB, ROOT, "hub"
            else:
                family = a.get("family") or {}
                host = (family.get("absorbed_by") or {}).get("id") if isinstance(family.get("absorbed_by"), dict) else None
                host = host if host and host in by_id else None
                node_key, parent, level = f"app:{aid}", (f"app:{host}" if host else HUB), ("module" if host else "app")
            operation = STATE_OPERATION.get(str(a.get("state", "")).lower(), "desconocida")
            if node_key == HUB:
                n = self._nodes[HUB]
                n.update(detail=a.get("purpose") or n["detail"], operation=operation)
            else:
                name = re.sub(r"\s·\s.*$", "", a.get("name") or aid)
                self._node(node_key, parent, level, name, app_id=aid, detail=a.get("purpose") or "", operation=operation,
                           meta={"url": a.get("url"), "port": a.get("port"), "folder": a.get("folder"), "kind": a.get("kind"),
                                 "state": a.get("state"), "manually_stopped": a.get("manually_stopped")})
            for cap in a.get("capabilities") or []:
                self._node(f"cap:{aid}:{folded(cap)}", node_key, "capability", str(cap), app_id=aid, operation=operation)

    def _from_manifests(self) -> dict[str, Any]:
        found = 0
        if not self.hoards_root or not self.hoards_root.is_dir():
            return {"ok": False, "error": "no hoards folder"}
        for manifest in sorted(self.hoards_root.glob("*/*/faustus-plugin.json")):
            try:
                d = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            aid = d.get("id") or manifest.parent.name
            key = HUB if aid in (HUB, "hoardlink") else f"app:{aid}"
            if key != HUB:
                self._node(key, HUB, "app", d.get("name") or aid, app_id=aid, detail=d.get("purpose") or "",
                           meta={"folder": str(manifest.parent)})
            for cap in d.get("capabilities") or []:
                self._node(f"cap:{aid}:{folded(cap)}", key, "capability", str(cap), app_id=aid)
            found += 1
        for folder in sorted(p for p in (self.hoards_root / "Faustusnt").glob("*") if p.is_dir()):
            aid = folded(folder.name).replace("'s", "").replace(" ", "-")
            self._node(f"app:{aid}", HUB, "app", folder.name, app_id=aid, detail="Sin conector de Faustus (Faustusnt).",
                       meta={"folder": str(folder), "faustusnt": True})
        return {"ok": True, "manifests": found}

    def _from_faustus(self, apps: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            catalog = _get(f"{self.faustus_url}/api/tools/catalog", timeout=30).get("tools", [])
            footprint = _get(f"{self.faustus_url}/api/tools/footprint", timeout=30)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
        labels = {s.get("source"): s.get("label") for s in footprint.get("by_source") or []}
        names = {folded(re.sub(r"\s·\s.*$", "", a.get("name") or "")): a["id"] for a in apps}
        names.update({folded(a["id"]): a["id"] for a in apps})
        names.update({"hoard hub": HUB, "hoardhub": HUB, "hoard link": HUB})
        native_groups: dict[str, list[dict[str, Any]]] = {}
        mapped, unmapped = 0, set()
        for t in catalog:
            name, desc = re.sub(r"^mcp__[^_]+(?:_[^_]+)*?__", "", t.get("name") or ""), (t.get("description") or "").strip().split("\n")[0][:300]
            mcp = t.get("mcp") or {}
            if not mcp:
                native_groups.setdefault(name.split("_")[0], []).append({"name": name, "desc": desc})
                continue
            label = labels.get(mcp.get("server_id")) or mcp.get("server_id") or "?"
            aid = names.get(folded(label)) or names.get(folded(label.replace("'s Hoard", "").replace(" Hoard", "")))
            status = "disponible" if mcp.get("status") == "connected" else "detenida"
            if aid:
                parent = HUB if aid == HUB else f"app:{aid}"
                if parent in self._nodes:
                    self._node(f"tool:{aid}:{name}", parent, "tool", name, app_id=aid, detail=desc, evidence="viva", operation=status)
                    mapped += 1
                    continue
            unmapped.add(label)
            gkey = f"mcp:{folded(label)}"
            self._node(gkey, ROOT, "module", f"MCP · {label}", app_id="faustus", detail="Servidor MCP conectado a Faustus.", evidence="viva",
                       operation=status)
            self._node(f"tool:{gkey}:{name}", gkey, "tool", name, app_id="faustus", detail=desc, evidence="viva", operation=status)
        group_key = "faustus:native"
        self._node(group_key, ROOT, "module", "Herramientas propias de Faustus", app_id="faustus", evidence="viva", operation="disponible",
                   detail=f"{sum(len(v) for v in native_groups.values())} herramientas nativas.")
        for prefix, tools in sorted(native_groups.items()):
            parent = group_key
            if len(tools) >= 3:
                parent = f"faustus:native:{prefix}"
                self._node(parent, group_key, "capability", prefix, app_id="faustus", evidence="viva", operation="disponible",
                           detail=f"{len(tools)} herramientas")
            for t in tools:
                self._node(f"tool:faustus:{t['name']}", parent, "tool", t["name"], app_id="faustus", detail=t["desc"], evidence="viva",
                           operation="disponible")
        return {"ok": True, "tools": len(catalog), "mapped_to_apps": mapped, "unmapped_servers": sorted(unmapped)}

    # ------------------------------------------------------------------ persisting

    def refresh(self) -> dict[str, Any]:
        self._nodes = {}
        report = self.collect()
        now = time.time()
        created = 0
        with self.store.tx() as c:
            for n in self._nodes.values():
                row = c.execute("SELECT id, operation FROM capabilities WHERE key=?", (n["key"],)).fetchone()
                if row is None:
                    c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail, evidence, operation, since, seen, meta) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (n["key"], n["parent_key"], n["level"], n["name"], n["app_id"], n["detail"], n["evidence"], n["operation"],
                               now, now, _j(n["meta"])))
                    created += 1
                else:
                    if row["operation"] != n["operation"]:
                        c.execute("INSERT INTO history(entity, entity_id, field, old, new, at, by, note) VALUES ('capabilities',?,?,?,?,?,?,?)",
                                  (row["id"], "operation", row["operation"], n["operation"], now, "tree", "refresh"))
                    c.execute("UPDATE capabilities SET parent_key=?, level=?, name=?, app_id=?, detail=COALESCE(NULLIF(?, ''), detail), "
                              "evidence=?, operation=?, seen=?, meta=? WHERE id=?",
                              (n["parent_key"], n["level"], n["name"], n["app_id"], n["detail"], n["evidence"], n["operation"], now,
                               _j(n["meta"]), row["id"]))
            # Tools are live evidence: one that Faustus no longer sees is not in the tree. Apps and capabilities stay
            # (an app being down does not remove what it can do). Only prune when Faustus answered this time.
            pruned = 0
            if (report.get("faustus") or {}).get("ok"):
                pruned = c.execute("DELETE FROM capabilities WHERE level='tool' AND seen<?", (now,)).rowcount
        self.store.set_meta("tree_refreshed_at", now)
        report.update(nodes=len(self._nodes), created=created, pruned_tools=pruned, refreshed_at=now)
        self.store.set_meta("tree_report", report)
        return report


_EVIDENCE_RANK = {"declarada": 0, "viva": 1, "probada": 2}


# ---------------------------------------------------------------------- reading the tree

def subtree(store: Store, root: str = ROOT, depth: int = 2, *, include_tools: bool = True) -> Optional[dict[str, Any]]:
    """Nested nodes from ``root`` down ``depth`` levels; each node carries child counts and its discoveries summary."""
    rows = store.q("SELECT key, parent_key, level, name, app_id, detail, evidence, operation, since, seen FROM capabilities")
    if not rows:
        return None
    children: dict[Optional[str], list[dict[str, Any]]] = {}
    by_key = {}
    for r in rows:
        if not include_tools and r["level"] == "tool":
            continue
        children.setdefault(r["parent_key"], []).append(r)
        by_key[r["key"]] = r
    if root not in by_key:
        return None
    discoveries = _discoveries_by_app(store)
    proofs = all_backing(store)
    order = {"hub": 0, "module": 1, "app": 2, "capability": 3, "tool": 4}

    def build(node: dict[str, Any], d: int) -> dict[str, Any]:
        kids = sorted(children.get(node["key"], []), key=lambda k: (order.get(k["level"], 9), k["name"].lower()))
        out = dict(node)
        out["children_count"] = len(kids)
        out["tools_count"] = sum(1 for k in kids if k["level"] == "tool")
        out["backed"] = is_backed(proofs.get(node["key"]))
        if out["backed"]:
            out["backing_evidence"] = proofs[node["key"]]["evidence"]
        if node["level"] in ("app", "module", "hub", "root"):
            out["discoveries"] = discoveries.get(node["app_id"], {})
        if d > 0:
            out["children"] = [build(k, d - 1) for k in kids]
        return out

    return build(by_key[root], max(0, min(depth, 8)))


def path_of(store: Store, key: str) -> list[dict[str, Any]]:
    out, seen = [], set()
    while key and key not in seen:
        seen.add(key)
        row = store.one("SELECT key, parent_key, level, name, app_id FROM capabilities WHERE key=?", (key,))
        if not row:
            break
        out.append(row)
        key = row["parent_key"]
    return list(reversed(out))


def find(store: Store, query: str, limit: int = 30, include_tools: bool = True) -> dict[str, Any]:
    """Which apps cover something: token + alias match over capability names, tool names/descriptions and app purposes.
    Results are grouped per app with the matching nodes and their path in the tree."""
    words = [w for w in re.findall(r"[a-z0-9]+", folded(query)) if w not in STOPWORDS]
    terms = set(words)
    for w in words:
        terms.update(ALIASES.get(w, "").split())
    terms = {t for t in terms if len(t) >= 2}
    if not terms:
        return {"query": query, "apps": []}
    rows = store.q("SELECT key, parent_key, level, name, app_id, detail, evidence, operation FROM capabilities")
    hits: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["level"] == "tool" and not include_tools:
            continue
        # what a description denies («Does not perform OCR») is not a capability: only the affirmed text is matched
        hay = f"{folded(r['name'])} {affirmed(folded(r['detail'] or ''))}"
        tokens = set(re.findall(r"[a-z0-9]+", hay))
        score = sum(2 if t in tokens else (1 if len(t) >= 4 and any(tok.startswith(t) for tok in tokens) else 0) for t in terms)
        if not score:
            continue
        app = r["app_id"] or "?"
        entry = hits.setdefault(app, {"app_id": app, "score": 0, "matches": []})
        weight = {"capability": 3, "tool": 2, "app": 1, "module": 1, "hub": 1, "root": 1}.get(r["level"], 1)
        entry["score"] += score * weight
        entry["matches"].append({"key": r["key"], "level": r["level"], "name": r["name"], "evidence": r["evidence"],
                                 "operation": r["operation"], "detail": (r["detail"] or "")[:200]})
    apps = sorted(hits.values(), key=lambda h: -h["score"])[:limit]
    for a in apps:
        node = store.one("SELECT key, name, operation, level FROM capabilities WHERE app_id=? AND level IN ('app','module','hub','root') "
                         "ORDER BY CASE level WHEN 'root' THEN 0 WHEN 'hub' THEN 1 WHEN 'app' THEN 2 ELSE 3 END LIMIT 1", (a["app_id"],))
        a["node"] = node
        a["path"] = [p["name"] for p in path_of(store, node["key"])] if node else []
        a["matches"] = sorted(a["matches"], key=lambda m: ({"capability": 0, "tool": 1}.get(m["level"], 2), m["name"]))[:12]
    return {"query": query, "terms": sorted(terms), "apps": apps}


def _discoveries_by_app(store: Store) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in store.q("SELECT target, state, COUNT(*) AS n FROM proposals WHERE target IS NOT NULL GROUP BY target, state"):
        out.setdefault(r["target"], {})[r["state"]] = r["n"]
    for r in store.q("SELECT target, COUNT(*) AS n FROM deliveries WHERE implementation IN ('integrada','parcial') GROUP BY target"):
        out.setdefault(r["target"], {})["entregas"] = r["n"]
    return out
