from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api.core.assets import AssetError, save_asset
from api.core.editor import (
    EditorError,
    active_pdf,
    get_state,
    rebuild,
    reset,
)
from api.core.storage import UploadError, load_meta

router = APIRouter(prefix="/documents", tags=["editor"])
assets_router = APIRouter(prefix="/assets", tags=["assets"])


class OpsPayload(BaseModel):
    ops: list[dict] = []


@router.get("/{doc_id}/editor")
async def editor_state(
    doc_id: str,
    page: int = Query(default=0, ge=0),
):
    try:
        return await run_in_threadpool(get_state, doc_id, page)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{doc_id}/ops")
async def update_ops(doc_id: str, payload: OpsPayload):
    try:
        version = await run_in_threadpool(rebuild, doc_id, payload.ops)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"version": version, "count": len(payload.ops)}


@router.post("/{doc_id}/reset", status_code=204)
async def reset_edits(doc_id: str):
    try:
        await run_in_threadpool(reset, doc_id)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{doc_id}/export")
async def export_document(doc_id: str):
    try:
        meta = await run_in_threadpool(load_meta, doc_id)
        path: Path = await run_in_threadpool(active_pdf, doc_id)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stem = Path(meta.get("filename", "document.pdf")).stem
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{stem}-edited.pdf",
    )


@assets_router.post("", status_code=201)
async def upload_asset(file: UploadFile = File(...)):
    try:
        result = await run_in_threadpool(save_asset, file.filename, file.file)
    except AssetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return result
