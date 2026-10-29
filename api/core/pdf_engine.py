from __future__ import annotations

import io
import unicodedata
from pathlib import Path

import pymupdf


class PdfError(Exception):
    pass


RTL_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)

ARABIC_LETTER_RANGES = (
    (0x0620, 0x064A),
    (0x066E, 0x06D3),
    (0x06FA, 0x06FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)

# MuPDF sometimes maps the Arabic lam glyph of a subset font to a Latin
# digraph glyph (DZ with caron / dental click), because the subset has no
# usable to-unicode entry for it. In Arabic text those code points never
# occur, so they can safely be repaired.
ARABIC_GLYPH_REPAIRS = {
    "\u01c0": "\u0644",
    "\u01c1": "\u0644",
    "\u01c4": "\u0644",
    "\u01c5": "\u0644",
    "\u01c6": "\u0644",
}


def _in_ranges(char: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in ranges)


def is_arabic(text: str) -> bool:
    return any(_in_ranges(char, RTL_RANGES) for char in text)


def _arabic_letter_count(text: str) -> int:
    return sum(1 for char in text if _in_ranges(char, ARABIC_LETTER_RANGES))


def _line_is_rtl(text: str, size_hint: float = 0.0) -> bool:
    """True when a line is dominated by Arabic script rather than Latin."""
    rtl = sum(1 for char in text if _in_ranges(char, RTL_RANGES))
    if not rtl:
        return False
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return rtl >= latin


def _logical_rtl(text: str) -> str:
    """Turn the visual run order MuPDF reports into readable logical text.

    Arabic letters are already stored right-to-left (so the extraction order is
    the logical order once the line is read from right to left), but a run made
    only of digits and separators - Arabic-Indic dates, card numbers - is
    mirrored and has to be reversed.
    """
    if not is_arabic(text):
        return text
    if _arabic_letter_count(text) == 0:
        text = text[::-1]
    for broken, fixed in ARABIC_GLYPH_REPAIRS.items():
        text = text.replace(broken, fixed)
    return unicodedata.normalize("NFKC", text)


def _span_entry(span: dict, direction) -> dict:
    x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
    color = int(span.get("color", 0))
    text = span.get("text", "")
    return {
        "text": text,
        "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
        "origin": [round(v, 2) for v in span.get("origin", (x0, y1))],
        "font": span.get("font", ""),
        "size": round(float(span.get("size", 0)), 2),
        "flags": int(span.get("flags", 0)),
        "color": f"#{color:06x}",
        "direction": [round(direction[0], 4), round(direction[1], 4)],
    }


def _merge_rtl_line(entries: list[dict]) -> dict:
    """One editable block per visual line instead of one block per glyph run."""
    ordered = sorted(entries, key=lambda item: -item["bbox"][0])
    text = "".join(item["text"] for item in ordered)
    size = max(item["size"] for item in ordered)
    x0 = min(item["bbox"][0] for item in ordered)
    y0 = min(item["bbox"][1] for item in ordered)
    x1 = max(item["bbox"][2] for item in ordered)
    y1 = max(item["bbox"][3] for item in ordered)
    text = _logical_rtl(text)
    return {
        "text": text,
        "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
        "origin": [round(x1, 2), round(y1 - size * 0.2, 2)],
        "font": ordered[0]["font"],
        "size": size,
        "flags": ordered[0]["flags"],
        "color": ordered[0]["color"],
        "direction": [-1.0, 0.0],
        "rtl": True,
        "fragments": len(entries),
    }


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
            raw = [_span_entry(span, direction) for span in line.get("spans", [])]
            entries = [entry for entry in raw if entry["text"].strip()]
            if not entries:
                continue
            line_text = "".join(entry["text"] for entry in raw)
            if len(entries) > 1 and _line_is_rtl(line_text):
                spans.append(_merge_rtl_line(raw))
            else:
                for entry in entries:
                    if is_arabic(entry["text"]):
                        entry["text"] = _logical_rtl(entry["text"])
                        entry["rtl"] = True
                    spans.append(entry)
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
