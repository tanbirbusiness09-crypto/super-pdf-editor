from __future__ import annotations

import io
from pathlib import Path

import pymupdf


class PdfError(Exception):
    pass


def inspect_pdf(path: Path) -> list[dict]:
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise PdfError("This PDF is password protected.")
            pages: list[dict] = []
            for page in doc:
                rect = page.rect
                pages.append(
                    {
                        "index": page.number,
                        "width": round(rect.width, 2),
                        "height": round(rect.height, 2),
                        "rotation": page.rotation,
                    }
                )
            if not pages:
                raise PdfError("This PDF has no pages.")
            return pages
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError("The file is not a readable PDF.") from exc


def render_page(path: Path, page_index: int, scale: float = 2.0) -> bytes:
    scale = max(0.4, min(scale, 4.0))
    try:
        with pymupdf.open(path) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                raise PdfError("Page not found.")
            page = doc.load_page(page_index)
            matrix = pymupdf.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            return pixmap.tobytes("png")
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError("Unable to render this page.") from exc


def extract_spans(path: Path, page_index: int) -> list[dict]:
    try:
        with pymupdf.open(path) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                raise PdfError("Page not found.")
            page = doc.load_page(page_index)
            data = page.get_text("dict")
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError("Unable to read text from this page.") from exc

    spans: list[dict] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1.0, 0.0))
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                color = int(span.get("color", 0))
                spans.append(
                    {
                        "text": text,
                        "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                        "origin": [round(v, 2) for v in span.get("origin", (x0, y1))],
                        "font": span.get("font", ""),
                        "size": round(float(span.get("size", 0)), 2),
                        "flags": int(span.get("flags", 0)),
                        "color": f"#{color:06x}",
                        "direction": [round(direction[0], 4), round(direction[1], 4)],
                    }
                )
    return spans


def image_to_pdf(image_path: Path, dest: Path) -> None:
    from PIL import Image, ImageOps

    try:
        with Image.open(image_path) as raw:
            image = ImageOps.exif_transpose(raw)
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            else:
                image = image.convert("RGB")

            dpi_info = image.info.get("dpi")
            dpi = 96.0
            if dpi_info and isinstance(dpi_info, tuple) and 50 < dpi_info[0] < 600:
                dpi = float(dpi_info[0])

            pixel_width, pixel_height = image.size
            page_width = pixel_width * 72.0 / dpi
            page_height = pixel_height * 72.0 / dpi

            pdf = pymupdf.open()
            page = pdf.new_page(width=page_width, height=page_height)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=92)
            page.insert_image(page.rect, stream=buffer.getvalue())
            pdf.save(dest)
            pdf.close()
    except Exception as exc:
        raise PdfError("Unable to convert this image.") from exc
