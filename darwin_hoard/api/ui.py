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
