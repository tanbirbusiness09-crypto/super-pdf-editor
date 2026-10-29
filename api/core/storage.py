from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from .config import (
    ALLOWED_EXTENSIONS,
    CHUNK_SIZE,
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
)
from .pdf_engine import PdfError, image_to_pdf, inspect_pdf

META_FILE = "meta.json"
PDF_FILE = "document.pdf"


class UploadError(Exception):
    pass


def document_dir(doc_id: str) -> Path:
    if not doc_id or not all(c in "0123456789abcdef" for c in doc_id):
        raise UploadError("Invalid document id.")
    path = UPLOAD_DIR / doc_id
    if not path.is_dir():
        raise UploadError("Document not found.")
    return path


def document_pdf(doc_id: str) -> Path:
    path = document_dir(doc_id) / PDF_FILE
    if not path.is_file():
        raise UploadError("Document file is missing.")
    return path


def load_meta(doc_id: str) -> dict:
    meta_path = document_dir(doc_id) / META_FILE
    if not meta_path.is_file():
        raise UploadError("Document metadata is missing.")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def list_documents(limit: int = 12) -> list[dict]:
    items: list[dict] = []
    if not UPLOAD_DIR.is_dir():
        return items
    for meta_path in UPLOAD_DIR.glob(f"*/{META_FILE}"):
        try:
            items.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return items[:limit]


def delete_document(doc_id: str) -> None:
    path = document_dir(doc_id)
    shutil.rmtree(path, ignore_errors=True)


def save_document(filename: str, stream: BinaryIO) -> dict:
    safe_name = Path(filename or "document").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadError(
            "Unsupported file type. Use PDF, PNG, JPG, WEBP, BMP or TIFF."
        )

    doc_id = uuid.uuid4().hex[:12]
    target_dir = UPLOAD_DIR / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)

    kind = "pdf" if suffix == ".pdf" else "image"
    source_path = target_dir / f"source{suffix}"
    size = 0

    try:
        with source_path.open("wb") as out:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadError("File is larger than 100 MB.")
                out.write(chunk)

        if size == 0:
            raise UploadError("The file is empty.")

        pdf_path = target_dir / PDF_FILE
        if kind == "image":
            image_to_pdf(source_path, pdf_path)
        else:
            shutil.move(str(source_path), str(pdf_path))

        pages = inspect_pdf(pdf_path)

        meta = {
            "id": doc_id,
            "filename": safe_name,
            "kind": kind,
            "size": size,
            "pageCount": len(pages),
            "pages": pages,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        (target_dir / META_FILE).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        return meta
    except (UploadError, PdfError):
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise UploadError("Unable to store the uploaded file.") from exc
