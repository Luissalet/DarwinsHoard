"""Routes for the bundled page. Everything it shows comes from the same handlers as the agent tools."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import query, tree
from ..agent_tools import TOOLS_BY_NAME
from ..errors import DarwinError
from ..hoard_link import family
from .deps import services, tool

router = APIRouter()


class CallBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    arguments: Optional[dict[str, Any]] = None


@router.get("/api/overview")
def overview(request: Request):
    return query.overview(services(request).store)


@router.get("/api/discoveries")
def discoveries(request: Request, q: str = "", state: str = "", target: str = "", channel: str = "", kind: str = "",
                pinned: Optional[bool] = None, radar_from: Optional[int] = None, radar_to: Optional[int] = None,
                order: str = "recent", limit: int = 50, offset: int = 0):
    return tool(request, "darwin_find", {"query": q, "state": state, "target": target, "channel": channel, "kind": kind,
                                         "pinned": pinned, "radar_from": radar_from, "radar_to": radar_to, "order": order,
                                         "limit": max(1, min(limit, 500)), "offset": max(0, offset)})


@router.get("/api/discoveries/{source_id}")
def discovery(request: Request, source_id: int):
    return tool(request, "darwin_source", {"id": source_id})


@router.get("/api/tree")
def tree_get(request: Request, root: str = tree.ROOT, depth: int = 2, tools: bool = True):
    return tool(request, "darwin_tree", {"root": root, "depth": depth, "tools": tools})


@router.post("/api/tree/refresh")
def tree_refresh(request: Request):
    return services(request).refresh_tree()


@router.get("/api/capabilities/find")
def cap_find(request: Request, q: str, limit: int = 15):
    return tool(request, "darwin_capability_find", {"query": q, "limit": max(1, min(limit, 60))})


@router.get("/api/suits")
def suits_list(request: Request, status: str = ""):
    return tool(request, "darwin_suits", {"status": status})


@router.get("/api/suits/{slug}")
def suit_get(request: Request, slug: str):
    return tool(request, "darwin_suit_get", {"slug": slug})


@router.put("/api/suits/{slug}")
def suit_put(request: Request, slug: str, body: dict[str, Any]):
    return tool(request, "darwin_suit_save", {**body, "slug": slug})


@router.delete("/api/suits/{slug}")
def suit_delete(request: Request, slug: str):
    return tool(request, "darwin_suit_delete", {"slug": slug})


@router.post("/api/suits/seed")
def suits_seed(request: Request):
    return tool(request, "darwin_suits_seed")


@router.post("/api/suits/{slug}/evaluation")
def suit_evaluation(request: Request, slug: str, body: dict[str, Any]):
    """Import an evaluation exported by Pygmalion's Hoard (``pygmalion-suit-eval/1``); the suit becomes «evaluated»."""
    return tool(request, "darwin_suit_import_eval", {"result": body, "slug": slug})


@router.post("/api/evaluations")
def evaluation_import(request: Request, body: dict[str, Any]):
    """Same, with the suit taken from the file; the endpoint Pygmalion's Hoard posts to."""
    return tool(request, "darwin_suit_import_eval", {"result": body})


@router.post("/api/capabilities/mark")
def capability_mark(request: Request, body: dict[str, Any]):
    return tool(request, "darwin_capability_mark", body)


@router.get("/api/gaps")
def gaps_get(request: Request):
    return tool(request, "darwin_gaps")


@router.post("/api/gaps/reconcile")
def gaps_reconcile(request: Request, body: Optional[dict[str, Any]] = None):
    return tool(request, "darwin_gaps_reconcile", body or {})


@router.get("/api/coverage")
def coverage_get(request: Request, source_id: Optional[int] = None, text: str = ""):
    return tool(request, "darwin_coverage", {"source_id": source_id, "text": text})


@router.get("/api/radar/plan")
def radar_plan(request: Request, limit: int = 10, remember: bool = False):
    """The page looks without moving the baseline (remember=false); a schedule calls the tool, which remembers."""
    return tool(request, "darwin_radar_plan", {"limit": max(1, min(limit, 100)), "remember": remember})


@router.post("/api/radar/run")
def radar_run(request: Request, body: Optional[dict[str, Any]] = None):
    return tool(request, "darwin_radar_run", body or {})


@router.get("/api/watches")
def watches_get(request: Request):
    return tool(request, "darwin_watches")


@router.post("/api/watches")
def watches_add(request: Request, body: dict[str, Any]):
    return tool(request, "darwin_watch_add", body)


@router.post("/api/watches/check")
def watches_check(request: Request):
    return tool(request, "darwin_watches_check")


@router.patch("/api/watches/{watch_id}")
def watches_update(request: Request, watch_id: int, body: dict[str, Any]):
    return tool(request, "darwin_watch_update", {**body, "id": watch_id})


@router.delete("/api/watches/{watch_id}")
def watches_delete(request: Request, watch_id: int):
    return tool(request, "darwin_watch_update", {"id": watch_id, "delete": True})


@router.get("/api/proposals")
def proposals_get(request: Request, state: str = "", target: str = "", origin: str = "", q: str = "", limit: int = 100, offset: int = 0):
    return tool(request, "darwin_proposals", {"state": state, "target": target, "origin": origin, "query": q,
                                              "limit": max(1, min(limit, 500)), "offset": max(0, offset)})


@router.get("/api/filters")
def filters_get(request: Request):
    return tool(request, "darwin_saved_filters", {"action": "list"})


@router.put("/api/filters/{name}")
def filters_put(request: Request, name: str, body: dict[str, Any]):
    return tool(request, "darwin_saved_filters", {"action": "save", "name": name, "filter": body})


@router.delete("/api/filters/{name}")
def filters_delete(request: Request, name: str):
    return tool(request, "darwin_saved_filters", {"action": "delete", "name": name})


@router.get("/api/panel")
def panel_get(request: Request, app: str = "", space: str = "", project: str = "", limit: int = 8):
    return tool(request, "darwin_panel", {"app": app, "space": space, "project": project, "limit": max(1, min(limit, 30))})


@router.get("/api/targets")
def targets(request: Request):
    store = services(request).store
    names = {r["app_id"]: r["name"] for r in store.q("SELECT app_id, name FROM capabilities WHERE level IN ('app','module','hub','root')")}
    rows = query.overview(store)["targets"]
    return {"targets": [{**r, "name": names.get(r["target"], r["target"])} for r in rows]}


@router.get("/api/changes")
def changes(request: Request, since: Optional[float] = None):
    return query.changes_since(services(request).store, since if since is not None else time.time() - 7 * 86400)


@router.get("/api/inbox")
def inbox(request: Request, channel: str = "", limit: int = 100, offset: int = 0):
    return query.inbox(services(request).store, channel=channel, limit=max(1, min(limit, 500)), offset=max(0, offset))


@router.get("/api/proposals/{proposal_id}/thread")
def proposal_thread(request: Request, proposal_id: int):
    return services(request).proposal_thread(proposal_id)


@router.get("/api/accounts")
def accounts(request: Request):
    return services(request).accounts()


@router.post("/api/accounts/{site}/login")
def account_login(request: Request, site: str, finish: bool = False, cancel: bool = False):
    if site not in ("x", "instagram", "threads", "tiktok", "reddit", "facebook", "youtube"):
        raise DarwinError("invalid", f"Unknown site {site}.")
    try:
        return services(request).account_login(site, finish=finish, cancel=cancel)
    except RuntimeError as exc:
        raise DarwinError("unavailable", str(exc)) from exc


@router.get("/api/posts")
def posts_status(request: Request):
    return services(request).posts_job


@router.post("/api/posts")
def posts_start(request: Request, limit: int = 30):
    return services(request).start_posts(limit=max(1, min(limit, 300)))


@router.get("/api/triage")
def triage_status(request: Request):
    return services(request).triage_job


@router.post("/api/triage")
def triage_start(request: Request, channel: str = "", limit: int = 50):
    return services(request).start_triage(channel=channel[:30], limit=max(1, min(limit, 200)))


@router.get("/api/inbox/ocr")
def inbox_ocr_status(request: Request):
    return services(request).ocr_job


@router.post("/api/inbox/ocr")
def inbox_ocr_start(request: Request, limit: int = 60):
    return services(request).start_ocr(limit=max(1, min(limit, 500)))


@router.get("/api/captures/{capture_id}/media")
def capture_media(request: Request, capture_id: int):
    """The image a capture refers to, from Faustus's WhatsApp media folder (read only, never outside it)."""
    from fastapi.responses import FileResponse
    from ..ocr import media_path
    svc = services(request)
    row = svc.store.one("SELECT attachment FROM captures WHERE id=?", (capture_id,))
    path = media_path(svc.media_dir, (row or {}).get("attachment") or "") if row else None
    if path is None:
        raise DarwinError("not_found", "This capture has no image on disk.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/api/deliveries/verify")
def deliveries_verify(request: Request):
    return services(request).verify_deliveries()


@router.get("/api/repo-aliases")
def repo_aliases_get(request: Request):
    return services(request).repo_aliases()


@router.post("/api/repo-aliases")
def repo_aliases_set(request: Request, body: dict[str, Any]):
    return services(request).set_repo_alias(str(body.get("name") or ""), repo=str(body.get("repo") or ""), path=str(body.get("path") or ""),
                                            subdir=str(body.get("subdir") or ""), search=bool(body.get("search")), remove=bool(body.get("remove")))


@router.get("/api/settings")
def settings_get(request: Request):
    return services(request).settings


@router.put("/api/settings")
def settings_put(request: Request, body: dict[str, Any]):
    return services(request).update_settings(body)


@router.get("/api/ui/tools")
def ui_tools():
    return {"tools": sorted(TOOLS_BY_NAME)}


@router.post("/api/ui/call")
def ui_call(request: Request, body: CallBody):
    if body.name not in TOOLS_BY_NAME:
        raise DarwinError("not_found", f"Unknown tool: {body.name}")
    t0 = time.monotonic()
    ok, error = False, ""
    try:
        result = tool(request, body.name, body.arguments)
        ok = True
        return result
    except Exception as exc:  # noqa: BLE001 - re-raised: the app's handlers shape the response
        error = str(exc)[:200]
        raise
    finally:
        family.record_call(body.name, ok, int((time.monotonic() - t0) * 1000), caller="ui", error=error)
