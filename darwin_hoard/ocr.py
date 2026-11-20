"""Screenshots in the inbox: read them with the family's OCR and link the repositories and links they show.

Most of what the account holder sends to the Gittrend chat is a screenshot of a post, not a link. A capture with an image attachment and no
source goes through the OCR engine of the family (Kafka's, via ``hoard_link.fam_docs.ocr_image``); URLs found in the text are
taken as they are, bare ``owner/name`` mentions only once GitHub confirms the repository exists (OCR of a post is full of
``and/or``-shaped noise). When Kafka's engine gives the layout (Indra: the blocks of the page in reading order), each block (a post,
a repository card, an address bar) is read on its own and a link that wraps at the end of a line is joined back, so a list of
«github.com/owner/» + «repo» lines yields the repositories and not just their owners. The result is kept on the capture
(``declared.ocr``, with the blocks that held links), so an image is read once; a capture whose image shows nothing recognisable
stays in the inbox with the text that was read, for a person to finish.

Kafka may be stopped: ``chain`` asks the hub to start it and reads again, and when it still does not answer the picture is read
by the family's vision model instead (the text of a post, not a layout). A repository that GitHub does not know, because the
screenshot cut its name or the engine mixed two letters, is completed from the owner's repositories when exactly one fits;
otherwise it is not taken as a source and it is listed as unconfirmed."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from .canon import extract_refs, repo_of
from .store import Store

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MEDIA_NAME = re.compile(r"^[A-Za-z0-9_.-]{4,120}$")
MAX_CANDIDATES = 8          # GitHub checks per image (unauthenticated API: 60 an hour)
OcrFn = Callable[[str], dict[str, Any]]
RepoCheck = Callable[[str], Optional[bool]]   # True exists, False does not, None unknown (offline, rate limited)
#: Why an OCR call failed because nobody answered (not because the picture is unreadable): worth starting Kafka or using vision.
UNAVAILABLE = {"app_down", "hub_down", "timeout", "tool_missing", "app_missing"}
VISION_PROMPT = ("Transcribe all the text visible in this screenshot exactly as written, in reading order, one block per post or card "
                 "separated by a blank line. Keep every link, repository name (owner/name) and number character by character, and do "
                 "not complete, correct or invent anything that is cut off. Answer with the transcription only.")


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


TRUNCATED_GITHUB = re.compile(r"(?:https?://)?github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100}?)\s*(?:\.{2,}|…)")
RepoList = Callable[[str], Optional[list[str]]]   # the repository names of an owner; None when unknown
SPLIT_GITHUB = re.compile(r"github\s*[.,]\s*com\s*/\s*", re.IGNORECASE)


def github_owner_repos(owner: str, *, timeout: float = 8.0) -> Optional[list[str]]:
    """Names of an owner's public repositories (first 300; users and organisations alike)."""
    names: list[str] = []
    for page in (1, 2, 3):
        req = urllib.request.Request(f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}&sort=updated",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": "darwins-hoard"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return names or None
        names += [str(r.get("name") or "") for r in batch if isinstance(r, dict)]
        if len(batch) < 100:
            break
    return names


def complete_truncated(text: str, repo_list: RepoList = github_owner_repos) -> tuple[str, list[str]]:
    """Posts cut repository links short («github.com/addyosmani/age…»). Complete each one with the single repository of
    that owner whose name starts that way; one that cannot be completed loses its «github.com/», so it is only taken as
    a candidate that GitHub must confirm (and a cut name never is). Returns the text and the completions made."""
    done: list[str] = []
    cache: dict[str, Optional[list[str]]] = {}
    # Fast OCR engines split a link at its dots («github. com/ owner/repo»): join it back first.
    text = SPLIT_GITHUB.sub("github.com/", text)

    def fix(match: re.Match) -> str:
        owner, prefix = match.group(1), match.group(2).rstrip(".")
        if owner not in cache:
            cache[owner] = repo_list(owner)
        names = [n for n in (cache[owner] or []) if n.lower().startswith(prefix.lower())]
        if len(names) == 1:
            done.append(f"{owner}/{names[0]}")
            return f"https://github.com/{owner}/{names[0]} "
        return f"{owner}/{prefix}… "

    return TRUNCATED_GITHUB.sub(fix, text), done


LINKISH_END = re.compile(r"(?:github\s*\.\s*com|https?:/|www\.)\S*[/_-]$", re.IGNORECASE)
LINK_TAIL = re.compile(r"^[A-Za-z0-9_.~#/?=&%-]+(?=\s|$)")
SKIP_BLOCKS = {"Picture"}


def rejoin(text: str) -> str:
    """A link that wraps at the end of a line («github.com/owner/» + «repo», «…/agent-» + «skills») is joined back to the next
    line's first word. Only a link that ends in «/», «-» or «_» is taken as cut; a whole link at the end of a line stays as it is."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    out: list[str] = []
    for line in lines:
        head = LINK_TAIL.match(line.lstrip())
        if out and head and LINKISH_END.search(out[-1]):
            rest = line.lstrip()[head.end():].lstrip()
            out[-1] = out[-1] + head.group(0)
            if rest:
                out.append(rest)
            continue
        out.append(line)
    return "\n".join(out)


def segments(res: dict[str, Any]) -> list[dict[str, str]]:
    """The parts of a screenshot read one by one: each layout block Kafka returns (a post, a repository card, an address bar) in
    reading order, with its wrapped links joined, so the links of one post stay with that post and a line of one post never
    continues into the next; the whole text as one part when the engine gave no layout."""
    parts: list[dict[str, str]] = []
    for block in res.get("layout") or []:
        if not isinstance(block, dict) or block.get("label") in SKIP_BLOCKS:
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append({"label": str(block.get("label") or "Text"), "text": rejoin(text)})
    if not parts:
        text = str(res.get("text") or "")
        parts = [{"label": "text", "text": rejoin(text)}] if text.strip() else []
    return parts


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


def github_search_repos(owner: str, text: str, *, timeout: float = 8.0) -> Optional[list[str]]:
    """Names of an owner's repositories that GitHub's search finds for a word (for owners with more than the 300 repositories
    ``github_owner_repos`` reads); None when GitHub does not answer."""
    query = urllib.parse.quote(f"{text} in:name user:{owner}")
    req = urllib.request.Request(f"https://api.github.com/search/repositories?q={query}&per_page=30",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "darwins-hoard"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            items = json.loads(resp.read().decode("utf-8")).get("items") or []
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
        return None
    return [str(i.get("name") or "") for i in items if isinstance(i, dict)]


RAW_HOST = re.compile(r"^(?:https?://)?raw\.githubusercontent\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})", re.IGNORECASE)
RepoSearch = Callable[[str, str], Optional[list[str]]]   # (owner, word) -> repository names; None when unknown


def github_repo_of(url: str) -> Optional[str]:
    """``owner/name`` of the repository a GitHub link points into (the repository page, a file or a raw file); None for
    anything else, a profile included."""
    match = RAW_HOST.match((url or "").strip())
    if match:
        return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return repo_of(url) if "github.com" in (url or "").lower() else None


def skeletons(name: str) -> set[str]:
    """What a name looks like to an OCR engine: the pairs it mixes up (n/m, rn/m, vv/w, cl/d, 0/o, 1/i/l) folded together, so a
    name read as «hern» is still near «herm…»."""
    low = name.lower()
    out = set()
    for text in (low, low.replace("rn", "m"), low.replace("vv", "w").replace("cl", "d")):
        out.add(text.translate(str.maketrans({"0": "o", "1": "l", "i": "l", "n": "m"})))
    return out


def complete_repo(repo: str, repo_list: RepoList, repo_search: Optional[RepoSearch] = None, *, min_chars: int = 3) -> Optional[str]:
    """The one repository of the owner that a name GitHub does not know was meant to be: its name as a prefix (the screenshot
    cut it) or, failing that, its look-alike prefix (the engine confused letters). The owner's list is read first, GitHub's
    search when that has nothing; two candidates are no answer. Returns ``owner/name`` or None."""
    owner, _, name = repo.partition("/")
    if len(name) < min_chars:
        return None
    mine = skeletons(name)
    seen: dict[str, list[str]] = {}

    def pick(names: Optional[list[str]]) -> Optional[str]:
        names = [n for n in names or [] if n]
        exact = [n for n in names if n.lower().startswith(name.lower())]
        if len(set(exact)) == 1:
            return exact[0]
        if exact:
            return None
        near = [n for n in names if any(any(s.startswith(m) for m in mine) for s in skeletons(n))]
        return near[0] if len(set(near)) == 1 else None

    got = pick(repo_list(owner))
    if got is None and repo_search is not None:
        got = pick(repo_search(owner, name))
    return f"{owner}/{got}" if got else None


def chain(ocr: OcrFn, *, start_app: Optional[Callable[[], bool]] = None, vision: Optional[OcrFn] = None) -> OcrFn:
    """An OCR function that does not stop at a stopped Kafka: when nobody answers, ``start_app`` asks the hub to start it (true
    once it answers) and the picture is read again; when it still does not, ``vision`` reads it with the family's vision model.
    A picture Kafka answered about, even badly, is never sent anywhere else. The result says which way it was read
    (``engine_report.fallback``) so the capture keeps it."""
    def read(path: str) -> dict[str, Any]:
        res = ocr(path)
        if res.get("ok") or res.get("kind") not in UNAVAILABLE:
            return res
        reason = str(res.get("error") or "OCR unavailable")
        if start_app is not None and res.get("kind") in ("app_down", "hub_down") and start_app():
            res = ocr(path)
            if res.get("ok") or res.get("kind") not in UNAVAILABLE:
                if res.get("ok"):
                    res["engine_report"] = {"fallback": False, "reason": "started through the hub"}
                return res
        if vision is not None:
            seen = vision(path)
            if seen.get("ok"):
                seen["engine_report"] = {"fallback": True, "reason": f"{reason}; read with the vision model"[:200]}
                return seen
            reason += f"; vision: {seen.get('error') or 'failed'}"
        return {**res, "error": reason}
    return read


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
               on_progress: Optional[Callable[[int, int], None]] = None,
               repo_list: RepoList = github_owner_repos, repo_search: Optional[RepoSearch] = None) -> dict[str, Any]:
    """Read up to ``limit`` unread screenshots. Stops at the first sign that the OCR engine is unavailable.

    Every GitHub repository a screenshot shows, as a link or as a bare ``owner/name``, is asked of GitHub once per run. A
    repository GitHub does not know is completed from its owner's repositories when exactly one fits (see
    :func:`complete_repo`) and otherwise dropped and listed as unconfirmed; a link GitHub could not be asked about is kept."""
    todo = pending(store, limit=limit)
    done = linked = missing = 0
    found: list[str] = []
    cache: dict[str, Optional[bool]] = {}
    owners: dict[str, Optional[list[str]]] = {}
    fixes: dict[str, Optional[str]] = {}
    checks = 0

    def owner_repos(owner: str) -> Optional[list[str]]:       # one lookup per owner for the whole run, whatever the block
        if owner not in owners:
            owners[owner] = repo_list(owner)
        return owners[owner]

    def settle(repo: str) -> tuple[str, Optional[bool]]:
        """GitHub's word on ``owner/name``: the repository to use (completed when it was cut) and True / False / None (unknown)."""
        nonlocal checks
        if repo not in cache:
            if checks >= MAX_CANDIDATES:
                return repo, None
            checks += 1
            cache[repo] = repo_check(repo)
        if cache[repo] is False:
            if repo not in fixes:
                fixes[repo] = complete_repo(repo, owner_repos, repo_search)
            if fixes[repo]:
                cache.setdefault(fixes[repo], True)
                return fixes[repo], True
        return repo, cache[repo]

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
        completed: list[str] = []
        parts = segments(res)
        per_block: list[dict[str, Any]] = []
        for part in parts:                                    # each post or card on its own: its links stay with it
            refs_text, done_here = complete_truncated(part["text"], owner_repos)
            completed += [c for c in done_here if c not in completed]
            block_refs: list[str] = []
            for ref in extract_refs(refs_text):
                is_candidate = ref["kind"] == "candidate"
                repo = ref["raw"] if is_candidate else github_repo_of(ref["url"])
                url = ref["url"]
                sid = None
                if repo:
                    shown = repo
                    repo, verdict = settle(repo)
                    if repo != shown and repo not in completed:
                        completed.append(repo)
                    url = f"https://github.com/{repo}"
                    if verdict is None and is_candidate or verdict is False and not is_candidate:
                        if shown not in unverified:         # not taken: GitHub did not answer, or denies the link the picture shows
                            unverified.append(shown)
                    if not verdict and (is_candidate or verdict is False):
                        continue
                    sid = store.upsert_source(repo=repo, seen_at=cap.get("at"), meta=None if verdict else {"github_verified": False})
                if url in accepted:
                    block_refs.append(url)
                    continue
                if sid is None:
                    sid = store.upsert_source(url=url, seen_at=cap.get("at"))
                store.link_capture(cap["id"], sid)
                accepted.append(url)
                block_refs.append(url)
            if block_refs and res.get("layout"):
                per_block.append({"label": part["label"], "text": part["text"][:400], "refs": block_refs})
        declared = {"at": time.time(), "text": text[:4000], "refs": accepted, "unverified": unverified, "backend": res.get("backend") or "",
                    "completed": completed}
        if res.get("layout"):
            declared["blocks"] = per_block
            declared["layout_blocks"] = len(parts)
        report = res.get("engine_report")
        if isinstance(report, dict) and report.get("fallback"):
            declared["engine_fallback"] = str(report.get("reason") or "")[:200]
        store.set_capture_declared(cap["id"], "ocr", declared)
        done += 1
        linked += 1 if accepted else 0
        found.extend(accepted)
    if on_progress:
        on_progress(len(todo), len(todo))
    return {"read": done, "linked": linked, "missing": missing, "remaining": 0, "found": found}
