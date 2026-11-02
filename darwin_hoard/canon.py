"""Identity of a discovery: canonical URLs and repository keys.

Two captures of the same thing must land on the same source, whatever tracking parameters, ``www.``, trailing slash,
``/tree/main`` or letter case they came with. Repositories are keyed ``repo:owner/name`` in lower case (GitHub names are
case-insensitive); the GitHub numeric id, when known, is kept on the source so a renamed repository is recognised."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_", "mc_", "pk_")
TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "igsh", "igshid", "si", "ref", "ref_src", "ref_url", "s", "t",
                 "source", "feature", "trk", "_hsenc", "_hsmi", "mkt_tok", "spm", "share_id", "tab"}
KEEP_KEYS = {"v", "list", "id", "p", "q"}  # content parameters that must survive (YouTube v, forum ids...)

GITHUB_HOSTS = {"github.com", "www.github.com"}
# Social posts carry only share/tracking parameters (x.com adds ?a=… per share): the path is the identity.
SOCIAL_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com", "instagram.com", "threads.net", "threads.com",
                "tiktok.com", "linkedin.com", "bsky.app", "reddit.com", "old.reddit.com", "youtu.be"}
HOST_ALIASES = {"twitter.com": "x.com", "mobile.twitter.com": "x.com", "mobile.x.com": "x.com", "old.reddit.com": "reddit.com",
                "threads.com": "threads.net"}
_RESERVED = {"orgs", "topics", "trending", "collections", "sponsors", "marketplace", "features", "about", "settings",
             "login", "join", "search", "explore", "notifications", "pulls", "issues", "apps", "users", "site", "enterprise"}
REPO_RE = re.compile(r"(?<![\w.@/-])([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})(?![\w/-])")
URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+|(?<![\w@])(?:www\.)?github\.com/[^\s<>()\[\]\"'`]+", re.I)


def canonical_url(raw: str) -> str:
    """Normalise a URL: https, lower-case host without ``www.``, no fragment, no default port, tracking parameters
    removed, query sorted, no trailing slash (except the root). GitHub repository URLs collapse to the repository."""
    text = (raw or "").strip().strip(".,;:)»”\"'")
    if not text:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    parts = urlsplit(text)
    scheme = "https" if parts.scheme.lower() in ("http", "https") else parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    social = host in SOCIAL_HOSTS
    host = HOST_ALIASES.get(host, host)
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "")
    if host == "github.com":
        repo = _github_repo_from_path(path)
        if repo:
            return f"https://github.com/{repo[0]}/{repo[1]}"
    query = [] if social else [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
                               if k.lower() in KEEP_KEYS or not (k.lower() in TRACKING_KEYS or k.lower().startswith(TRACKING_PREFIXES))]
    query.sort()
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    if path == "/":
        path = ""
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def _github_repo_from_path(path: str) -> tuple[str, str] | None:
    bits = [b for b in path.split("/") if b]
    if len(bits) < 2 or bits[0].lower() in _RESERVED:
        return None
    owner, name = bits[0], bits[1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
        return None
    return owner, name


def repo_of(text: str) -> str | None:
    """``owner/name`` (original case) from a GitHub URL or a bare ``owner/name``; None otherwise."""
    value = (text or "").strip()
    if not value:
        return None
    if "github.com" in value.lower():
        parts = urlsplit(value if "://" in value else "https://" + value)
        repo = _github_repo_from_path(parts.path)
        return f"{repo[0]}/{repo[1]}" if repo else None
    match = REPO_RE.fullmatch(value)
    if match and "." not in match.group(1):
        return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return None


def repo_key(text: str) -> str | None:
    repo = repo_of(text)
    return f"repo:{repo.lower()}" if repo else None


def source_key(*, url: str = "", repo: str = "", title: str = "") -> str:
    """The unique key of a source: ``repo:owner/name``, ``url:<canonical>`` or ``idea:<hash of the title>``."""
    key = repo_key(repo) if repo else None
    if not key and url:
        key = repo_key(url)
    if key:
        return key
    if url:
        canon = canonical_url(url)
        if canon:
            return "url:" + canon
    norm = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not norm:
        raise ValueError("A source needs a URL, a repository or a title.")
    return "idea:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def extract_refs(text: str) -> list[dict[str, str]]:
    """URLs and bare ``owner/name`` mentions in free text (a chat message, OCR of a screenshot), de-duplicated by key.
    Bare mentions are only candidates: the caller verifies them (GitHub) before trusting them."""
    out: dict[str, dict[str, str]] = {}
    for m in URL_RE.finditer(text or ""):
        raw = m.group(0)
        key = source_key(url=raw)
        out.setdefault(key, {"key": key, "url": canonical_url(raw), "raw": raw, "kind": "url"})
    stripped = URL_RE.sub(" ", text or "")
    for m in REPO_RE.finditer(stripped):
        owner, name = m.group(1), m.group(2).removesuffix(".git")
        if name.lower() in ("s", "a", "o") or name.isdigit() or owner.isdigit():
            continue
        repo = f"{owner}/{name}"
        key = f"repo:{repo.lower()}"
        out.setdefault(key, {"key": key, "url": f"https://github.com/{repo}", "raw": repo, "kind": "candidate"})
    return list(out.values())
