"""Screenshots in the inbox: read them with the family's OCR and link the repositories and links they show.

Most of what Luis sends to the Gittrend chat is a screenshot of a post, not a link. A capture with an image attachment and no
source goes through the OCR engine of the family (Kafka's, via ``hoard_link.fam_docs.ocr_image``); URLs found in the text are
taken as they are, bare ``owner/name`` mentions only once GitHub confirms the repository exists (OCR of a post is full of
``and/or``-shaped noise). The result is kept on the capture (``declared.ocr``), so an image is read once; a capture whose image
shows nothing recognisable stays in the inbox with the text that was read, for a person to finish."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from .canon import extract_refs
from .store import Store

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MEDIA_NAME = re.compile(r"^[A-Za-z0-9_.-]{4,120}$")
MAX_CANDIDATES = 8          # GitHub checks per image (unauthenticated API: 60 an hour)
OcrFn = Callable[[str], dict[str, Any]]
RepoCheck = Callable[[str], Optional[bool]]   # True exists, False does not, None unknown (offline, rate limited)


def attachment_name(raw: str) -> str:
    """The media file name a capture refers to (the bridge stores ``<message id>.<ext>``); '' when none."""
    value = (raw or "").strip()
    if value[:1] in ('"', '{'):
        try:
            value = json.loads(value)
        except ValueError:
            value = value.strip('"')
    if isinstance(value, dict):
        value = value.get("file") or value.get("name") or value.get("path") or ""
    name = Path(str(value)).name
    return name if MEDIA_NAME.match(name) else ""


def media_path(media_dir: Path, raw: str) -> Optional[Path]:
    """The file inside ``media_dir`` (never outside it), or None."""
    name = attachment_name(raw)
    if not name:
        return None
    path = (media_dir / name).resolve()
    try:
        path.relative_to(media_dir.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def github_repo_exists(repo: str, *, timeout: float = 6.0) -> Optional[bool]:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", method="GET",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "darwins-hoard"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def pending(store: Store, *, limit: int = 60) -> list[dict[str, Any]]:
    """Inbox captures with an image attachment that were never read."""
    rows = store.q(
        "SELECT c.* FROM captures c WHERE c.source_id IS NULL AND c.attachment IS NOT NULL AND c.attachment NOT IN ('', '\"\"') "
        "AND NOT EXISTS (SELECT 1 FROM capture_sources cs WHERE cs.capture_id=c.id) ORDER BY c.at DESC LIMIT ?", (limit * 3,))
    out = []
    for row in rows:
        declared = row.get("declared") or {}
        if isinstance(declared, str):
            declared = json.loads(declared or "{}")
        if "ocr" in declared:
            continue
        if Path(attachment_name(row.get("attachment") or "")).suffix.lower() in IMAGE_EXTS:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def read_inbox(store: Store, media_dir: Path, ocr: OcrFn, *, repo_check: RepoCheck = github_repo_exists, limit: int = 60,
               on_progress: Optional[Callable[[int, int], None]] = None) -> dict[str, Any]:
    """Read up to ``limit`` unread screenshots. Stops at the first sign that the OCR engine is unavailable."""
    todo = pending(store, limit=limit)
    done = linked = missing = 0
    found: list[str] = []
    cache: dict[str, Optional[bool]] = {}
    for i, cap in enumerate(todo):
        if on_progress:
            on_progress(i, len(todo))
        path = media_path(media_dir, cap.get("attachment") or "")
        if path is None:
            store.set_capture_declared(cap["id"], "ocr", {"at": time.time(), "error": "image file not found"})
            missing += 1
            continue
        res = ocr(str(path))
        if not res.get("ok"):
            return {"read": done, "linked": linked, "missing": missing, "remaining": len(todo) - i, "found": found,
                    "error": res.get("error") or "OCR failed", "kind": res.get("kind") or "failed"}
        text = str(res.get("text") or "")
        accepted, unverified = [], []
        checks = 0
        for ref in extract_refs(text):
            if ref["kind"] == "candidate":
                repo = ref["raw"]
                if repo not in cache:
                    if checks >= MAX_CANDIDATES:
                        unverified.append(repo)
                        continue
                    checks += 1
                    cache[repo] = repo_check(repo)
                if cache[repo] is None:
                    unverified.append(repo)
                if not cache[repo]:
                    continue
                sid = store.upsert_source(repo=repo, seen_at=cap.get("at"))
            else:
                sid = store.upsert_source(url=ref["url"], seen_at=cap.get("at"))
            store.link_capture(cap["id"], sid)
            accepted.append(ref["url"])
        store.set_capture_declared(cap["id"], "ocr", {"at": time.time(), "text": text[:4000], "refs": accepted,
                                                       "unverified": unverified, "backend": res.get("backend") or ""})
        done += 1
        linked += 1 if accepted else 0
        found.extend(accepted)
    if on_progress:
        on_progress(len(todo), len(todo))
    return {"read": done, "linked": linked, "missing": missing, "remaining": 0, "found": found}
