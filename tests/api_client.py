"""Minimal client for the PDF Studio API, used by the smoke test."""

from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from pathlib import Path


class ApiError(RuntimeError):
    pass


class Api:
    def __init__(self, base: str, keep: bool = False) -> None:
        self.base = base.rstrip("/")
        self.keep = keep

    # -- low level -------------------------------------------------------
    def _open(self, request: urllib.request.Request, timeout: float = 300.0) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ApiError(f"{request.get_method()} {request.full_url} -> {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"cannot reach {self.base}: {exc.reason}") from exc

    def _json(self, request: urllib.request.Request) -> dict:
        return json.loads(self._open(request) or b"{}")

    # -- endpoints -------------------------------------------------------
    def health(self) -> bool:
        try:
            data = self._json(
                urllib.request.Request(f"{self.base}/api/health", method="GET")
            )
        except ApiError:
            return False
        return data.get("status") == "ok"

    def upload(self, path: Path) -> dict:
        boundary = "----pdfs" + uuid.uuid4().hex
        content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            f"{self.base}/api/documents",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        return self._json(request)

    def editor(self, doc_id: str, page: int = 0) -> dict:
        request = urllib.request.Request(
            f"{self.base}/api/documents/{doc_id}/editor?page={page}", method="GET"
        )
        return self._json(request)

    def put_ops(self, doc_id: str, ops: list[dict]) -> dict:
        request = urllib.request.Request(
            f"{self.base}/api/documents/{doc_id}/ops",
            data=json.dumps({"ops": ops}).encode(),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        return self._json(request)

    def render(self, doc_id: str, page: int = 0, scale: float = 2.0) -> bytes:
        request = urllib.request.Request(
            f"{self.base}/api/documents/{doc_id}/pages/{page}/render?scale={scale}",
            method="GET",
        )
        return self._open(request)

    def export(self, doc_id: str) -> bytes:
        request = urllib.request.Request(
            f"{self.base}/api/documents/{doc_id}/export", method="GET"
        )
        return self._open(request)

    def export_text(self, doc_id: str) -> str:
        import pymupdf

        data = self.export(doc_id)
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    def delete(self, doc_id: str) -> None:
        if self.keep:
            return
        request = urllib.request.Request(
            f"{self.base}/api/documents/{doc_id}", method="DELETE"
        )
        try:
            self._open(request, timeout=60)
        except ApiError:
            pass
