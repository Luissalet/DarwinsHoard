"""Where each repository name used by the Ágora, the radar and the trackers lives today.

Repositories were renamed, folded into other apps (as a subfolder, usually without their history) and moved from
D:\\LocalAI and the Desktop to E:\\Development\\IA\\Hoards\\Faustusables and …\\Faustusnt on 29/30-10-2026. A delivery keeps
the name it was declared with; this map says which local repository (and which subfolder) holds that code now, so the
commit check looks in the right place. Luis's own entries (setting ``repo_aliases``) win over the built-in ones."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Old name → {"repo": today's name in the hub's inventory, "subdir": folder of a folded app, "search": every repository}.
BUILTIN_ALIASES: dict[str, dict[str, Any]] = {
    "HoardLink": {"repo": "Hoard Hub"},
    "Hoard Link": {"repo": "Hoard Hub"},
    "FieldDex": {"repo": "Hoard Dex"},
    "TalosHoard": {"repo": "Talos's Hoard"},
    "Writers Hoard": {"repo": "Writers hoard desktop"},
    "Writer's Hoard": {"repo": "Writers hoard desktop"},
    "GamerHoard": {"repo": "Gamer Hoard"},
    "CookHoard": {"repo": "Cook Hoard"},
    "HomeHoard": {"repo": "Home Hoard"},
    "BloodArrows": {"space": "blood-arrows"},
    "Blood Arrows": {"space": "blood-arrows"},
    "Odysseus": {"repo": "Faustus"},
    r"D:\LocalAI\faustus": {"repo": "Faustus"},
    r"D:\LocalAI\odysseus": {"repo": "Faustus"},
    # D:\LocalAI was the umbrella folder of Faustus, HoardLink and the first Hoards: look in every repository.
    "LocalAI": {"search": True},
    r"D:\LocalAI": {"search": True},
    # Apps folded into another one (code copied into a subfolder; provenance/ records the source commit).
    "Galton's Hoard": {"repo": "Pygmalion's Hoard", "subdir": "galton_hoard"},
    "Midas's Hoard": {"repo": "Coase's Hoard", "subdir": "midas_hoard"},
    "Disk Hoard": {"repo": "Talos's Hoard", "subdir": "diskhoard"},
    "Argus's Hoard": {"repo": "Talos's Hoard", "subdir": "argus"},
    "Funes's Hoard": {"repo": "Talos's Hoard", "subdir": "funes_hoard"},
    "Echo's Hoard": {"repo": "Talos's Hoard", "subdir": "echo"},
    "Cassandra's Hoard": {"repo": "Talos's Hoard", "subdir": "cassandra_hoard"},
    "Borges's Hoard": {"repo": "Writers hoard desktop", "subdir": "publishing/borges"},
    "Tantalus's Hoard": {"repo": "Hermes's Hoard", "subdir": "tantalus_hoard"},
    "Phileas's Hoard": {"repo": "Hermes's Hoard", "subdir": "phileas_hoard"},
    "Babel's Hoard": {"repo": "Vitruvius's Hoard", "subdir": "babels_hoard"},
    "Theseus": {"repo": "Vitruvius's Hoard", "subdir": "theseus"},
    "Gulliver's Hoard": {"repo": "Vulcan's Hoard", "subdir": "vulcan/studio_native/gulliver"},
    "Laplace's Hoard": {"repo": "Nightingale's Hoard", "subdir": "fusion"},
}


def norm(name: Any) -> str:
    """« Galton's Hoard », « GaltonsHoard », « galton hoard » → the same key."""
    return re.sub(r"s(?=hoard$)", "", re.sub(r"[^a-z0-9]", "", str(name or "").lower().replace("'s", "")))


def _clean(value: Any) -> dict[str, Any] | None:
    """An alias as Luis may type it: a repository name, a folder path, or {repo|path|space, subdir, search}."""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return {"path": value} if (":" in value[:3] or value.startswith(("\\\\", "/"))) else {"repo": value}
    if isinstance(value, Mapping):
        out = {k: str(value[k]).strip() for k in ("repo", "path", "space", "subdir") if value.get(k)}
        if value.get("search"):
            out["search"] = True
        return out or None
    return None


def merged_aliases(custom: Mapping | None) -> dict[str, dict[str, Any]]:
    out = {k: dict(v, origin="builtin") for k, v in BUILTIN_ALIASES.items()}
    by_key = {norm(k): k for k in out}
    for name, value in (custom or {}).items():
        alias = _clean(value)
        if alias is None:
            continue
        out.pop(by_key.get(norm(name), ""), None)  # Luis's entry replaces the built-in one for the same name
        out[str(name)] = dict(alias, origin="settings")
    return out


def provenance_commit(repo_path: str, old_name: str) -> str:
    """Last upstream commit a folded app was copied from, as the target repository's provenance files record it."""
    want = norm(old_name)
    root = Path(repo_path)
    for pattern in ("provenance/**/*.json", "*/provenance/*.json"):
        for f in sorted(root.glob(pattern))[:40]:
            if f.name.lower() not in ("source.json", "sources.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for entry in data if isinstance(data, list) else [data]:
                if not isinstance(entry, Mapping) or not entry.get("commit"):
                    continue
                label = entry.get("source") or str(entry.get("repository") or entry.get("origin") or "").rstrip("/").rsplit("/", 1)[-1]
                if norm(label) == want or (f.parent.name and norm(f.parent.name) == want.removesuffix("hoard")):
                    return str(entry["commit"])
    return ""


class RepoMap:
    """Resolves repository names against the hub's inventory, the Ágora spaces' workspaces and the aliases."""

    def __init__(self, *, hub_repos: Mapping[str, str], faustus_dir: str = "", spaces: Mapping[str, str] | None = None,
                 custom: Mapping | None = None):
        self.hub = {str(n): str(p) for n, p in hub_repos.items() if n and p}
        if faustus_dir:
            self.hub.setdefault("Faustus", str(faustus_dir))
        self.known = {norm(n): {"path": p, "name": n} for n, p in self.hub.items()}
        self.spaces = {str(k): str(v) for k, v in (spaces or {}).items() if v}
        self.aliases = merged_aliases(custom)
        self._by_norm = {norm(k): v for k, v in self.aliases.items()}
        self._prov: dict[tuple[str, str], str] = {}

    def resolve(self, name: str) -> dict[str, Any] | None:
        """{'path', 'name', 'subdir', 'source_commit', 'via'} or {'search': True} or None (unknown name)."""
        alias = self._by_norm.get(norm(name)) or self._by_norm.get(norm(f"{name} Hoard"))
        if alias is None:
            hit = self.known.get(norm(name)) or self.known.get(norm(f"{name} Hoard"))
            if hit:
                return {**hit, "subdir": "", "via": "inventory"}
            ws = self.spaces.get(str(name))
            return {"path": ws, "name": str(name), "subdir": "", "via": "agora_space"} if ws else None
        if alias.get("search"):
            return {"search": True, "name": str(name), "via": alias["origin"]}
        if alias.get("path"):
            base = {"path": alias["path"], "name": Path(alias["path"]).name}
        elif alias.get("space"):
            ws = self.spaces.get(alias["space"])
            base = {"path": ws, "name": alias["space"]} if ws else None
        else:
            base = self.known.get(norm(alias.get("repo")))
        if not base:
            return None
        out = {**base, "subdir": alias.get("subdir", ""), "via": alias["origin"]}
        if out["subdir"]:
            key = (out["path"], str(name))
            if key not in self._prov:
                self._prov[key] = provenance_commit(out["path"], str(name))
            out["source_commit"] = self._prov[key]
        return out

    def roots(self, names: Iterable[str]) -> dict[str, dict[str, Any]]:
        """What ``verify_deliveries`` takes: every hub repository, every Ágora space and each name in ``names``.
        Only folders that are a repository themselves (a workspace like D:\\LocalAI is not)."""
        out: dict[str, dict[str, Any]] = {n: {"path": p, "name": n} for n, p in self.hub.items()}
        for sid, ws in self.spaces.items():
            out.setdefault(sid, {"path": ws, "name": sid})
        # Every alias too: an Ágora resolution may name an old repository no delivery uses (« Tantalus main 57da1e2 »).
        for name in [*self.aliases, *names]:
            if name:
                hit = self.resolve(name)
                if hit:
                    out[name] = hit
        return {k: v for k, v in out.items() if v.get("search") or (v.get("path") and (Path(v["path"]) / ".git").exists())}

    def table(self, counts: Mapping[str, int] | None = None) -> list[dict[str, Any]]:
        """Every alias with where it lands today and how many deliveries use that name (for the page)."""
        counts = {norm(k): v for k, v in (counts or {}).items()}
        rows = []
        for name, alias in sorted(self.aliases.items(), key=lambda kv: kv[0].lower()):
            hit = self.resolve(name)
            rows.append({"name": name, "origin": alias["origin"], "repo": alias.get("repo", ""), "path": alias.get("path", ""),
                         "space": alias.get("space", ""), "subdir": alias.get("subdir", ""), "search": bool(alias.get("search")),
                         "resolved_path": (hit or {}).get("path", ""), "resolved_name": (hit or {}).get("name", ""),
                         "source_commit": (hit or {}).get("source_commit", ""),
                         "ok": bool(hit and (hit.get("search") or (Path(hit["path"]) / ".git").exists()
                                             and (not hit.get("subdir") or (Path(hit["path"]) / hit["subdir"]).exists()))),
                         "deliveries": counts.get(norm(name), 0)})
        return rows
