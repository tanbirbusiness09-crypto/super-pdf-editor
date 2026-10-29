from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from api.core.editor import active_pdf
from api.core.pdf_engine import PdfError, extract_spans, render_page
from api.core.storage import (
    UploadError,
    delete_document,
    list_documents,
    load_meta,
    save_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _handle(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def get_documents(limit: int = Query(default=12, ge=1, le=50)):
    return {"items": await run_in_threadpool(list_documents, limit)}


@router.post("", status_code=201)
async def upload_document(file: UploadFile = File(...)):
    try:
        meta = await run_in_threadpool(save_document, file.filename, file.file)
    except (UploadError, PdfError) as exc:
        raise _handle(exc) from exc
    finally:
        await file.close()
    return meta


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    try:
        return await run_in_threadpool(load_meta, doc_id)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{doc_id}", status_code=204)
async def remove_document(doc_id: str):
    try:
        await run_in_threadpool(delete_document, doc_id)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{doc_id}/pages/{page_index}/render")
async def render_document_page(
    doc_id: str,
    page_index: int,
    scale: float = Query(default=2.0, ge=0.4, le=4.0),
):
    try:
        path = await run_in_threadpool(active_pdf, doc_id)
        png = await run_in_threadpool(render_page, path, page_index, scale)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PdfError as exc:
        raise _handle(exc) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{doc_id}/pages/{page_index}/text")
async def get_page_text(doc_id: str, page_index: int):
    try:
        path = await run_in_threadpool(active_pdf, doc_id)
        spans = await run_in_threadpool(extract_spans, path, page_index)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PdfError as exc:
        raise _handle(exc) from exc
    return {"page": page_index, "spans": spans}

