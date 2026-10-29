from __future__ import annotations

import io
import json
import os
import threading
import time
import unicodedata
from html import escape as html_escape
from pathlib import Path

import pymupdf

from .assets import AssetError, asset_bytes
from .fonts import (
    _builtin_alias,
    _has_arabic,
    _is_bold_name,
    resolve_font,
)
from .ocr import available as ocr_available
from .ocr import read_page as ocr_read_page
from .pdf_engine import extract_spans
from .storage import document_dir, document_pdf, load_meta

WORKING_FILE = "working.pdf"
OPS_FILE = "ops.json"
TEMP_FILE = "working.tmp.pdf"
MAX_OPS = 500

LOCK = threading.Lock()

OP_TYPES = {
    "add_text",
    "replace_text",
    "delete_text",
    "add_image",
    "replace_image",
    "transform_image",
    "delete_image",
    "erase_area",
}


class EditorError(Exception):
    pass


def active_pdf(doc_id: str) -> Path:
    directory = document_dir(doc_id)
    working = directory / WORKING_FILE
    if working.is_file():
        return working
    return document_pdf(doc_id)


def load_session(doc_id: str) -> tuple[list[dict], int]:
    path = document_dir(doc_id) / OPS_FILE
    if not path.is_file():
        return [], 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], 0
    ops = data.get("ops") or []
    version = int(data.get("version") or 0)
    if not isinstance(ops, list):
        return [], version
    return ops, version


def _parse_color(value: str | None) -> tuple[float, float, float]:
    text = (value or "#000000").lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        return (
            int(text[0:2], 16) / 255.0,
            int(text[2:4], 16) / 255.0,
            int(text[4:6], 16) / 255.0,
        )
    except (ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def _text_width(alias: str, fontfile: Path | None, text: str, size: float) -> float | None:
    try:
        if fontfile:
            font = pymupdf.Font(fontfile=str(fontfile))
            return font.text_length(text, fontsize=size)
        return pymupdf.get_text_length(text, fontname=alias, fontsize=size)
    except Exception:
        return None


def _html_color(value: str | None) -> str:
    text = str(value or "#111111")
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return "#111111"


def _insert_rtl_text(
    page: pymupdf.Page, op: dict, text: str, size: float, bold: bool
) -> None:
    bbox = op.get("bbox")
    origin = op.get("origin") or [0.0, 0.0]
    if bbox and len(bbox) == 4:
        right = float(bbox[2])
        top = float(bbox[1])
        bottom = float(bbox[3])
    else:
        right = min(
            page.rect.width - 2.0,
            float(origin[0]) + max(size * 4.0, len(text) * size * 0.55),
        )
        top = float(origin[1]) - size
        bottom = float(origin[1]) + size * 0.3

    top = max(0.0, top - size * 0.12)
    box = pymupdf.Rect(
        0.0,
        top,
        max(2.0, right),
        max(bottom + size * 0.3, top + size * 1.35),
    )
    markup = (
        '<div style="margin:0;padding:0;line-height:1.05;direction:rtl;'
        f'font-size:{size}px;'
        f'font-weight:{"bold" if bold else "normal"};'
        f'color:{_html_color(op.get("color"))};white-space:pre-wrap;">'
        f"{html_escape(text)}</div>"
    )
    try:
        page.insert_htmlbox(box, markup)
    except Exception as exc:
        raise EditorError(f"Could not write text on page {page.number + 1}.") from exc


def _insert_text(doc: pymupdf.Document, page: pymupdf.Page, op: dict) -> None:
    text = str(op.get("text") or "")
    if not text.strip():
        return

    size = max(3.0, min(float(op.get("size") or 11.0), 300.0))
    origin = op.get("origin") or [0.0, 0.0]
    point = pymupdf.Point(float(origin[0]), float(origin[1]))
    color = _parse_color(op.get("color"))
    font_name = str(op.get("font") or "Helvetica")
    bold = bool(op.get("bold"))
    italic = bool(op.get("italic"))

    if _has_arabic(text):
        _insert_rtl_text(page, op, text, size, bold)
        return

    alias, fontfile = resolve_font(doc, page, font_name, text, bold=bold, italic=italic)
    if fontfile:
        try:
            page.insert_font(fontname=alias, fontfile=str(fontfile))
        except Exception:
            alias, fontfile = _builtin_alias(font_name, bold=bold, italic=italic), None

    bbox = op.get("bbox")
    if bbox and len(bbox) == 4 and op.get("fit", True):
        available = max(1.0, float(bbox[2]) - float(bbox[0]))
        width = _text_width(alias, fontfile, text, size)
        if width and width > available:
            size = max(3.0, size * available / width)

    extra: dict = {}
    if bold and fontfile is not None and not _is_bold_name(font_name):
        extra = {
            "render_mode": 2,
            "border_width": 0.05,
        }

    try:
        page.insert_text(
            point,
            text,
            fontsize=size,
            fontname=alias,
            color=color,
            overlay=True,
            **extra,
        )
    except Exception as exc:
        raise EditorError(f"Could not write text on page {page.number + 1}.") from exc


def _redact(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    images: int,
    graphics: int,
    text: int,
) -> None:
    page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=images, graphics=graphics, text=text)


def _normalized_rect(value) -> pymupdf.Rect:
    try:
        rect = pymupdf.Rect(value)
    except Exception as exc:
        raise EditorError("Invalid area for this object.") from exc
    rect.normalize()
    if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
        raise EditorError("The selected area is too small.")
    return rect


def _insert_image(page: pymupdf.Page, op: dict) -> None:
    rect = _normalized_rect(op.get("rect"))
    try:
        data = asset_bytes(str(op.get("asset") or ""))
    except AssetError as exc:
        raise EditorError(str(exc)) from exc
    try:
        page.insert_image(rect, stream=data, keep_proportion=False, overlay=True)
    except Exception as exc:
        raise EditorError(f"Could not place the image on page {page.number + 1}.") from exc


def _sample_background(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[float, float, float]:
    try:
        scale = 2.0
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        width, height = pixmap.width, pixmap.height
        x0 = max(0, int(rect.x0 * scale))
        y0 = max(0, int(rect.y0 * scale))
        x1 = min(width - 1, int(rect.x1 * scale))
        y1 = min(height - 1, int(rect.y1 * scale))

        samples: list[tuple[int, int, int]] = []
        step_x = max(1, (x1 - x0) // 30)
        step_y = max(1, (y1 - y0) // 30)
        for offset in (2, 4, 6, 9):
            for x in range(x0, x1 + 1, step_x):
                for y in (y0 - offset, y1 + offset):
                    if 0 <= y < height:
                        samples.append(pixmap.pixel(x, y))
            for y in range(y0, y1 + 1, step_y):
                for x in (x0 - offset, x1 + offset):
                    if 0 <= x < width:
                        samples.append(pixmap.pixel(x, y))

        if not samples:
            return (1.0, 1.0, 1.0)

        channels = [[sample[index] for sample in samples] for index in range(3)]
        channels = [sorted(values) for values in channels]
        middle = len(samples) // 2
        return tuple(channels[index][middle] / 255.0 for index in range(3))
    except Exception:
        return (1.0, 1.0, 1.0)


def _rect_has_text(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    try:
        data = page.get_text("dict", clip=rect)
    except Exception:
        return False
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if str(span.get("text") or "").strip():
                    return True
    return False


def _rect_pixels(page: pymupdf.Page, rect: pymupdf.Rect) -> bytes:
    try:
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2.0, 2.0), clip=rect, alpha=False
        )
        return pixmap.samples
    except Exception:
        return b""


def _pixel_difference(before: bytes, after: bytes) -> float:
    if not before or len(before) != len(after):
        return 255.0
    total = 0
    for left, right in zip(before, after):
        total += abs(left - right)
    return total / len(before)


def _rect_covered_by_image(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    try:
        for info in page.get_images(full=True):
            for image_rect in page.get_image_rects(info[0]):
                overlap = image_rect & rect
                if overlap.is_empty:
                    continue
                if overlap.get_area() >= rect.get_area() * 0.9:
                    return True
    except Exception:
        return False
    return False


def _erase_patch(page: pymupdf.Page, rect: pymupdf.Rect) -> bytes | None:
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except Exception:
        return None

    try:
        scale = 3.0
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale), clip=rect, alpha=False
        )
        width, height, channels = pixmap.width, pixmap.height, pixmap.n
        if width < 8 or height < 8:
            return None

        pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            height, width, channels
        )[:, :, :3].astype(np.float32)
        gray = pixels.mean(axis=2)

        smoothed = np.asarray(
            Image.fromarray(gray.astype(np.uint8))
            .filter(ImageFilter.MedianFilter(size=5))
            .filter(ImageFilter.GaussianBlur(radius=1.2))
        ).astype(np.float32)
        local_max = np.asarray(
            Image.fromarray(smoothed.astype(np.uint8)).filter(
                ImageFilter.MaxFilter(size=31)
            )
        ).astype(np.float32)
        contrast = local_max - gray
        mask = contrast > 10.0
        if not mask.any():
            return None
        mask = (
            np.asarray(
                Image.fromarray((mask.astype(np.uint8) * 255)).filter(
                    ImageFilter.MaxFilter(size=5)
                )
            )
            > 0
        )

        result = pixels.copy()
        known = ~mask
        background = known.copy()
        for _ in range(256):
            if known.all():
                break
            total = np.zeros_like(result)
            count = np.zeros(mask.shape, dtype=np.float32)
            total[1:, :] += result[:-1, :] * known[:-1, :, None]
            count[1:, :] += known[:-1, :]
            total[:-1, :] += result[1:, :] * known[1:, :, None]
            count[:-1, :] += known[1:, :]
            total[:, 1:] += result[:, :-1] * known[:, :-1, None]
            count[:, 1:] += known[:, :-1]
            total[:, :-1] += result[:, 1:] * known[:, 1:, None]
            count[:, :-1] += known[:, 1:]
            fillable = (~known) & (count > 0)
            if not fillable.any():
                break
            result[fillable] = total[fillable] / count[fillable][:, None]
            known = known | fillable

        alpha = mask.astype(np.float32)[:, :, None]
        blurred = np.asarray(
            Image.fromarray(pixels.astype(np.uint8)).filter(ImageFilter.BoxBlur(1))
        ).astype(np.float32)
        high_pass = pixels - blurred
        grain_sigma = float(np.std(high_pass[background])) if background.any() else 0.0
        grain_sigma = min(max(grain_sigma, 0.0), 8.0)
        rng = np.random.default_rng(int(rect.x0 * 7 + rect.y0 * 13))
        grain = rng.normal(0.0, grain_sigma, (height, width, 1)).astype(np.float32)
        blended = pixels * (1.0 - alpha) + result * alpha + grain * alpha

        buffer = io.BytesIO()
        Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8)).save(
            buffer, format="PNG"
        )
        return buffer.getvalue()
    except Exception:
        return None


def _erase_area(page: pymupdf.Page, op: dict) -> None:
    rect = _normalized_rect(op.get("rect"))

    if _rect_has_text(page, rect):
        before = _rect_pixels(page, rect)
        _redact(
            page,
            rect,
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        after = _rect_pixels(page, rect)
        if _pixel_difference(before, after) >= 2.0:
            return

    if _rect_covered_by_image(page, rect):
        patch = _erase_patch(page, rect)
        if patch:
            try:
                page.insert_image(
                    rect, stream=patch, keep_proportion=False, overlay=True
                )
                return
            except Exception:
                pass

    color = _sample_background(page, rect)
    try:
        page.draw_rect(rect, color=None, fill=color, width=0, overlay=True)
    except Exception as exc:
        raise EditorError(f"Could not erase the area on page {page.number + 1}.") from exc


def _apply_op(doc: pymupdf.Document, op: dict) -> None:
    if not isinstance(op, dict):
        raise EditorError("Invalid edit operation.")

    kind = op.get("type")
    if kind not in OP_TYPES:
        raise EditorError(f"Unsupported edit operation: {kind}")

    try:
        page_index = int(op.get("page", 0))
    except (TypeError, ValueError) as exc:
        raise EditorError("Invalid page number.") from exc

    if page_index < 0 or page_index >= doc.page_count:
        raise EditorError("Edit target page does not exist.")

    page = doc.load_page(page_index)

    if kind == "add_text":
        _insert_text(doc, page, op)

    elif kind == "replace_text":
        bbox = _normalized_rect(op.get("bbox"))
        _redact(
            page,
            bbox,
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        _insert_text(doc, page, op)

    elif kind == "delete_text":
        bbox = _normalized_rect(op.get("bbox"))
        _redact(
            page,
            bbox,
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

    elif kind == "add_image":
        _insert_image(page, op)

    elif kind == "replace_image":
        rect = _normalized_rect(op.get("rect"))
        _redact(
            page,
            rect,
            images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_NONE,
        )
        _insert_image(page, op)

    elif kind == "delete_image":
        rect = _normalized_rect(op.get("rect"))
        _redact(
            page,
            rect,
            images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_NONE,
        )

    elif kind == "erase_area":
        _erase_area(page, op)


def _collapse_image_ops(ops: list[dict]) -> list[dict]:
    collapsed: list[dict] = []
    positions: dict[str, int] = {}

    for op in ops:
        if not isinstance(op, dict):
            collapsed.append(op)
            continue

        kind = op.get("type")
        asset = str(op.get("asset") or "")

        if kind == "transform_image" and asset in positions:
            new_rect = op.get("newRect") or op.get("new_rect")
            if isinstance(new_rect, (list, tuple)) and len(new_rect) == 4:
                index = positions[asset]
                base = dict(collapsed[index])
                base["rect"] = new_rect
                collapsed[index] = base
            continue

        if kind == "add_image" and asset:
            positions[asset] = len(collapsed)

        collapsed.append(op)

    return collapsed


def rebuild(doc_id: str, ops: list[dict]) -> int:
    if len(ops) > MAX_OPS:
        raise EditorError("Too many edits in one document. Export and start again.")

    with LOCK:
        directory = document_dir(doc_id)
        source = directory / "document.pdf"
        target = directory / WORKING_FILE
        temp = directory / TEMP_FILE
        version = int(time.time() * 1000)

        if not ops:
            target.unlink(missing_ok=True)
            temp.unlink(missing_ok=True)
            (directory / OPS_FILE).write_text(
                json.dumps({"ops": [], "version": version}, ensure_ascii=False),
                encoding="utf-8",
            )
            return version

        doc = pymupdf.open(source)
        try:
            for op in _collapse_image_ops(ops):
                _apply_op(doc, op)
            doc.save(str(temp), deflate=True)
        finally:
            doc.close()

        os.replace(temp, target)
        (directory / OPS_FILE).write_text(
            json.dumps({"ops": ops, "version": version}, ensure_ascii=False),
            encoding="utf-8",
        )
        return version


def _page_images(doc: pymupdf.Document, page: pymupdf.Page) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple] = set()
    try:
        images = page.get_images(full=True)
    except Exception:
        return items

    for info in images:
        xref = info[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            key = (xref, round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "xref": xref,
                    "rect": [
                        round(rect.x0, 2),
                        round(rect.y0, 2),
                        round(rect.x1, 2),
                        round(rect.y1, 2),
                    ],
                    "width": info[2],
                    "height": info[3],
                }
            )
    return items


def _rects_match(left, right) -> bool:
    try:
        return all(
            abs(float(left[index]) - float(right[index])) <= 0.75
            for index in range(4)
        )
    except (TypeError, ValueError, IndexError):
        return False


def _rect_overlap_ratio(rect, other) -> float:
    try:
        left = [float(value) for value in rect]
        right = [float(value) for value in other]
    except (TypeError, ValueError):
        return 0.0
    if len(left) != 4 or len(right) != 4:
        return 0.0
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    return intersection / area


def _normalized_text(value) -> str:
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split()).lower()


def _edited_text_spans(ops: list[dict], page_index: int) -> list[dict]:
    active: list[dict] = []
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        if int(op.get("page", 0)) != page_index:
            continue
        if op.get("type") not in ("add_text", "replace_text"):
            continue
        bbox = op.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        try:
            rect = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue
        text = str(op.get("text") or "").strip()
        if not text:
            continue
        removed = False
        for later in ops[index + 1 :]:
            if not isinstance(later, dict) or later.get("type") != "erase_area":
                continue
            if int(later.get("page", 0)) != page_index:
                continue
            if _rect_overlap_ratio(rect, later.get("rect") or []) > 0.5:
                removed = True
                break
        if removed:
            continue
        active = [
            item
            for item in active
            if _rect_overlap_ratio(rect, item["bbox"]) <= 0.5
        ]
        size = max(3.0, float(op.get("size") or 11.0))
        origin = op.get("origin") or [rect[0], rect[3] - size * 0.2]
        arabic = _has_arabic(text)
        active.append(
            {
                "text": text,
                "bbox": rect,
                "origin": [float(origin[0]), float(origin[1])],
                "font": str(op.get("font") or "Helvetica"),
                "size": round(size, 2),
                "flags": 16 if op.get("bold") else 0,
                "color": str(op.get("color") or "#111111"),
                "direction": [-1.0, 0.0] if arabic else [1.0, 0.0],
                "bold": bool(op.get("bold")),
                "rtl": arabic,
                "edited": True,
            }
        )
    return active


def _span_belongs_to_edit(span: dict, edit: dict) -> bool:
    if _rect_overlap_ratio(span.get("bbox") or [], edit["bbox"]) >= 0.5:
        return True
    span_text = _normalized_text(span.get("text"))
    edit_text = _normalized_text(edit.get("text"))
    if not span_text or not edit_text or span_text not in edit_text:
        return False
    span_bbox = span.get("bbox") or [0, 0, 0, 0]
    span_center_y = (span_bbox[1] + span_bbox[3]) / 2
    edit_center_y = (edit["bbox"][1] + edit["bbox"][3]) / 2
    tolerance = max(2.5, (span_bbox[3] - span_bbox[1]) * 0.8)
    if abs(span_center_y - edit_center_y) > tolerance:
        return False
    margin = max(6.0, (edit["bbox"][2] - edit["bbox"][0]) * 0.6)
    span_center_x = (span_bbox[0] + span_bbox[2]) / 2
    return edit["bbox"][0] - margin <= span_center_x <= edit["bbox"][2] + margin


def _filtered_ocr_spans(
    doc_id: str,
    page_index: int,
    spans: list[dict],
    ops: list[dict],
) -> list[dict]:
    if not ocr_available():
        return []

    cache_dir = document_dir(doc_id) / "ocr"
    cache_file = cache_dir / f"page-{page_index}.json"
    cached = cache_file.is_file()
    source = document_pdf(doc_id)
    if not cached:
        try:
            with pymupdf.open(source) as source_doc:
                if page_index < 0 or page_index >= source_doc.page_count:
                    return []
                source_page = source_doc.load_page(page_index)
                if source_page.get_text("text").strip():
                    return []
                if not source_page.get_images(full=True):
                    return []
        except Exception:
            return []

    try:
        raw = ocr_read_page(source, page_index, cache_dir)
    except Exception:
        return []
    if not raw:
        return []

    real = [
        span.get("bbox")
        for span in spans
        if isinstance(span.get("bbox"), (list, tuple))
    ]
    blocked: list[list[float]] = []
    for op in _collapse_image_ops(ops):
        if not isinstance(op, dict):
            continue
        try:
            if int(op.get("page", 0)) != page_index:
                continue
        except (TypeError, ValueError):
            continue
        kind = op.get("type")
        rect = None
        if kind == "erase_area":
            rect = op.get("rect")
        elif kind in ("add_image", "replace_image", "delete_image"):
            rect = op.get("rect")
        elif kind == "transform_image":
            rect = op.get("newRect") or op.get("new_rect")
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            blocked.append([float(value) for value in rect])

    result: list[dict] = []
    for item in raw:
        rect = item.get("bbox")
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            continue
        if any(_rect_overlap_ratio(rect, other) > 0.35 for other in real):
            continue
        if any(_rect_overlap_ratio(rect, other) > 0.25 for other in blocked):
            continue
        result.append(item)
    return result


def get_state(doc_id: str, page_index: int) -> dict:
    ops, version = load_session(doc_id)
    path = active_pdf(doc_id)
    meta = load_meta(doc_id)

    with pymupdf.open(path) as doc:
        if page_index < 0 or page_index >= doc.page_count:
            raise EditorError("Page not found.")
        page = doc.load_page(page_index)
        spans = extract_spans(path, page_index)
        images = _page_images(doc, page)
        page_count = doc.page_count

        ocr_spans = _filtered_ocr_spans(doc_id, page_index, spans, ops)
        if ocr_spans:
            spans = sorted(
                spans + ocr_spans,
                key=lambda item: (
                    round(float(item["bbox"][1]), 1),
                    round(float(item["bbox"][0]), 1),
                ),
            )

    edited_spans = _edited_text_spans(ops, page_index)
    if edited_spans:
        spans = [
            span
            for span in spans
            if not any(_span_belongs_to_edit(span, edit) for edit in edited_spans)
        ]
        spans = sorted(
            spans + edited_spans,
            key=lambda item: (
                round(float(item["bbox"][1]), 1),
                round(float(item["bbox"][0]), 1),
            ),
        )

    erase_rects = [
        op.get("rect")
        for op in ops
        if op.get("type") == "erase_area" and int(op.get("page", 0)) == page_index
    ]
    if erase_rects:
        images = [
            image
            for image in images
            if not any(_rects_match(image["rect"], rect) for rect in erase_rects)
        ]

    return {
        "id": doc_id,
        "filename": meta.get("filename", "document.pdf"),
        "version": version,
        "pageCount": page_count,
        "page": page_index,
        "spans": spans,
        "images": images,
        "ops": ops,
        "pages": meta.get("pages", []),
        "ocrAvailable": ocr_available(),
    }


def reset(doc_id: str) -> None:
    directory = document_dir(doc_id)
    with LOCK:
        for name in (WORKING_FILE, OPS_FILE, TEMP_FILE):
            (directory / name).unlink(missing_ok=True)
