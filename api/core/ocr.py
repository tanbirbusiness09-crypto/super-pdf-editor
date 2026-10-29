from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter, ImageOps

from .config import DATA_DIR

OCR_VERSION = 3
OCR_DPI = 220
CACHE_DIR = "ocr"
TESSDATA_DIR = DATA_DIR / "tessdata"
MIN_CONFIDENCE = 25.0
LOCK = threading.Lock()

TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


def tesseract_path() -> str | None:
    env = os.environ.get("PDFS_TESSERACT")
    if env and Path(env).is_file():
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    candidates = list(TESSERACT_CANDIDATES)
    if local:
        candidates.append(Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def available() -> bool:
    return tesseract_path() is not None


def _languages() -> str:
    env = os.environ.get("PDFS_OCR_LANGS")
    if env:
        return env
    if TESSDATA_DIR.is_dir():
        codes = [
            code
            for code in ("eng", "ara", "ben")
            if (TESSDATA_DIR / f"{code}.traineddata").is_file()
        ]
        if codes:
            return "+".join(codes)
    return "eng"


def _tessdata_args() -> list[str]:
    if TESSDATA_DIR.is_dir() and any(TESSDATA_DIR.glob("*.traineddata")):
        return ["--tessdata-dir", str(TESSDATA_DIR)]
    return []


def _is_rtl(text: str) -> bool:
    arabic = sum(1 for char in text if 0x0600 <= ord(char) <= 0x06FF)
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return arabic > latin


def _clean_text(text: str) -> str:
    text = text.replace("\u200e", "").replace("\u200f", "")
    return " ".join(text.split())


def _parse_tsv(tsv_path: Path, scale: float) -> list[dict]:
    words: list[dict] = []
    try:
        content = tsv_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return words

    for row in content.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = _clean_text(cols[11])
        if not text:
            continue
        try:
            confidence = float(cols[10])
            left = float(cols[6]) / scale
            top = float(cols[7]) / scale
            width = float(cols[8]) / scale
            height = float(cols[9]) / scale
        except ValueError:
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        if not any(char.isalnum() for char in text):
            continue
        words.append(
            {
                "text": text,
                "x0": left,
                "y0": top,
                "x1": left + width,
                "y1": top + height,
                "confidence": confidence,
            }
        )
    return words


def _group_words(words: list[dict]) -> list[dict]:
    if not words:
        return []

    words = sorted(words, key=lambda item: (item["y0"], item["x0"]))
    rows: list[list[dict]] = []
    for word in words:
        center = (word["y0"] + word["y1"]) / 2
        height = max(1.0, word["y1"] - word["y0"])
        target = None
        for row in rows:
            row_top = min(item["y0"] for item in row)
            row_bottom = max(item["y1"] for item in row)
            row_center = (row_top + row_bottom) / 2
            row_height = max(1.0, row_bottom - row_top)
            if abs(center - row_center) <= 0.55 * max(height, row_height):
                target = row
                break
        if target is None:
            rows.append([word])
        else:
            target.append(word)

    spans: list[dict] = []
    median_height = sorted(item["y1"] - item["y0"] for item in words)[len(words) // 2]
    gap_limit = max(6.5, 0.9 * median_height)

    for row in rows:
        row.sort(key=lambda item: item["x0"])
        clusters: list[list[dict]] = [[row[0]]]
        for previous, word in zip(row, row[1:]):
            if word["x0"] - previous["x1"] > gap_limit:
                clusters.append([word])
            else:
                clusters[-1].append(word)

        for cluster in clusters:
            rtl = _is_rtl(" ".join(item["text"] for item in cluster))
            ordered = sorted(cluster, key=lambda item: item["x0"], reverse=rtl)
            text = _clean_text(" ".join(item["text"] for item in ordered))
            if len(text) < 2:
                continue

            x0 = min(item["x0"] for item in cluster)
            y0 = min(item["y0"] for item in cluster)
            x1 = max(item["x1"] for item in cluster)
            y1 = max(item["y1"] for item in cluster)
            heights = sorted(item["y1"] - item["y0"] for item in cluster)
            height_pt = heights[len(heights) // 2]
            size = height_pt * (1.0 if rtl else 1.15)
            confidence = sum(item["confidence"] for item in cluster) / len(cluster)
            spans.append(
                {
                    "text": text,
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "height": height_pt,
                    "size": max(4.0, min(size, 160.0)),
                    "confidence": round(confidence, 1),
                    "rtl": rtl,
                }
            )
    return spans


def _iou(left: list[float], right: list[float]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area_left = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    area_right = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / (area_left + area_right - intersection)


def _overlap_ratio(left: list[float], right: list[float]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area_left = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    return intersection / area_left


def _merge_spans(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged = list(primary)
    for span in secondary:
        if span["confidence"] < 55:
            continue
        if any(
            _iou(span["bbox"], other["bbox"]) > 0.2
            or _overlap_ratio(span["bbox"], other["bbox"]) > 0.5
            or _overlap_ratio(other["bbox"], span["bbox"]) > 0.5
            for other in merged
        ):
            continue
        merged.append(span)
    merged.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return merged


def _pixel_array(pix: pymupdf.Pixmap) -> np.ndarray:
    data = np.frombuffer(pix.samples, dtype=np.uint8)
    data = data.reshape(pix.height, pix.stride)[:, : pix.width * 3]
    return data.reshape(pix.height, pix.width, 3)


def _sample_color(array: np.ndarray, bbox: list[float], scale: float) -> str:
    height, width = array.shape[:2]
    x0 = max(0, int(bbox[0] * scale))
    y0 = max(0, int(bbox[1] * scale))
    x1 = min(width, int(bbox[2] * scale) + 1)
    y1 = min(height, int(bbox[3] * scale) + 1)
    if x1 <= x0 or y1 <= y0:
        return "#111111"

    region = array[y0:y1, x0:x1].reshape(-1, 3).astype(np.int32)
    if not region.size:
        return "#111111"
    luminance = (region[:, 0] * 299 + region[:, 1] * 587 + region[:, 2] * 114) // 1000
    order = np.argsort(luminance)
    sample = region[order[: max(1, len(order) // 10)]]
    red, green, blue = sample.mean(axis=0).round().astype(int)
    if (int(red) * 299 + int(green) * 587 + int(blue) * 114) // 1000 > 225:
        return "#111111"
    return f"#{int(red):02x}{int(green):02x}{int(blue):02x}"


def _stroke_ratio(array: np.ndarray, bbox: list[float], scale: float, height_pt: float) -> float:
    height, width = array.shape[:2]
    x0 = max(0, int(bbox[0] * scale))
    y0 = max(0, int(bbox[1] * scale))
    x1 = min(width, int(bbox[2] * scale) + 1)
    y1 = min(height, int(bbox[3] * scale) + 1)
    height_px = height_pt * scale
    if x1 <= x0 or y1 <= y0 or height_px <= 0:
        return 0.0

    region = array[y0:y1, x0:x1].astype(np.int32)
    luminance = (region[:, :, 0] * 299 + region[:, :, 1] * 587 + region[:, :, 2] * 114) // 1000
    background = float(np.median(luminance))
    threshold = min(190.0, background - 45.0)
    mask = luminance < threshold
    if mask.mean() < 0.01:
        return 0.0

    runs: list[int] = []
    for row in mask:
        padded = np.concatenate(([0], row.astype(np.int8), [0]))
        changes = np.flatnonzero(np.diff(padded))
        if len(changes) >= 2:
            lengths = changes[1::2] - changes[0::2]
            runs.extend(int(value) for value in lengths if value > 0)
    if not runs:
        return 0.0
    return float(np.median(runs)) / max(1.0, height_px)


def _preprocess(pix: pymupdf.Pixmap, plain: Path, sharp: Path) -> None:
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    gray = ImageOps.autocontrast(image.convert("L"))
    gray.save(plain)
    gray.filter(ImageFilter.SHARPEN).save(sharp)


def _run_pass(binary: str, image: Path, langs: str, scale: float, tag: str) -> list[dict]:
    out_base = image.with_name(f"out-{tag}")
    command = [
        binary,
        str(image),
        str(out_base),
        "-l",
        langs,
        "--psm",
        "3",
        "--dpi",
        str(OCR_DPI),
        *_tessdata_args(),
        "tsv",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    tsv_path = out_base.with_suffix(".tsv")
    if not tsv_path.is_file():
        return []
    return _group_words(_parse_tsv(tsv_path, scale))


def _run_ocr(source: Path, page_index: int) -> list[dict]:
    binary = tesseract_path()
    if not binary:
        return []

    scale = OCR_DPI / 72.0
    temp_dir = Path(tempfile.mkdtemp(prefix="pdfs-ocr-"))
    plain_path = temp_dir / "page.png"
    sharp_path = temp_dir / "page-sharp.png"
    try:
        with pymupdf.open(source) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                return []
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            _preprocess(pix, plain_path, sharp_path)

        languages = _languages()
        primary = _run_pass(binary, plain_path, languages, scale, "primary")
        ordered = "+".join(
            code for code in ("ara", "ben", "eng") if code in languages.split("+")
        )
        secondary = (
            _run_pass(binary, sharp_path, ordered, scale, "secondary")
            if ordered and ordered != languages
            else []
        )
        spans = _merge_spans(primary, secondary)
        if not spans:
            return []

        array = _pixel_array(pix)
        for span in spans:
            bbox = span["bbox"]
            span["color"] = _sample_color(array, bbox, scale)
            ratio = _stroke_ratio(array, bbox, scale, span["height"])
            span["bold"] = ratio >= 0.12
            span["stroke"] = round(ratio, 4)
            span.pop("height", None)
            span.pop("rtl", None)
        return spans
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def read_page(source: Path, page_index: int, cache_dir: Path) -> list[dict]:
    if not available():
        return []

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"page-{page_index}.json"
    try:
        stat = source.stat()
    except OSError:
        return []
    key = {
        "version": OCR_VERSION,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "langs": _languages(),
        "dpi": OCR_DPI,
    }

    if cache_file.is_file():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if data.get("key") == key and isinstance(data.get("spans"), list):
                return data["spans"]
        except (OSError, json.JSONDecodeError):
            pass

    with LOCK:
        if cache_file.is_file():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if data.get("key") == key and isinstance(data.get("spans"), list):
                    return data["spans"]
            except (OSError, json.JSONDecodeError):
                pass

        raw = _run_ocr(source, page_index)
        spans = []
        for item in raw:
            size = round(float(item["size"]), 2)
            bbox = [round(float(value), 2) for value in item["bbox"]]
            spans.append(
                {
                    "text": item["text"],
                    "bbox": bbox,
                    "origin": [bbox[0], round(bbox[3] - size * 0.18, 2)],
                    "font": "OCR",
                    "size": size,
                    "flags": 16 if item.get("bold") else 0,
                    "color": item.get("color", "#111111"),
                    "direction": [1.0, 0.0],
                    "confidence": item["confidence"],
                    "bold": bool(item.get("bold")),
                    "ocr": True,
                }
            )
        try:
            cache_file.write_text(
                json.dumps({"key": key, "spans": spans}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return spans
