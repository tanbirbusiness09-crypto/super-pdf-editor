from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf

from .config import DATA_DIR

FONT_CACHE = DATA_DIR / "fonts"
BANGLA_FONTS = [
    Path(r"C:\Windows\Fonts\Nirmala.ttc"),
    Path(r"C:\Windows\Fonts\Nirmala.ttf"),
    Path(r"C:\Windows\Fonts\Vrinda.ttf"),
    Path(r"C:\Windows\Fonts\Shonar.ttf"),
]
ARABIC_FONTS = [
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\tahoma.ttf"),
    Path(r"C:\Windows\Fonts\times.ttf"),
]

BUILTIN_ALIASES = {
    "helv": "helv",
    "hebo": "hebo",
    "heit": "heit",
    "hebi": "hebi",
    "tiro": "tiro",
    "tibo": "tibo",
    "tiit": "tiit",
    "tibi": "tibi",
    "cour": "cour",
    "cobo": "cobo",
    "coit": "coit",
    "cobi": "cobi",
}


def _clean(name: str) -> str:
    base = name.split("+")[-1]
    return base.lower().replace("-", "").replace(" ", "")


def _has_non_latin(text: str) -> bool:
    return any(ord(char) > 0x24F for char in text)


def _has_arabic(text: str) -> bool:
    return any(
        0x0600 <= ord(char) <= 0x06FF
        or 0x0750 <= ord(char) <= 0x077F
        or 0x08A0 <= ord(char) <= 0x08FF
        or 0xFB50 <= ord(char) <= 0xFDFF
        or 0xFE70 <= ord(char) <= 0xFEFF
        for char in text
    )


def _has_bengali(text: str) -> bool:
    return any(0x0980 <= ord(char) <= 0x09FF for char in text)


def _first_font(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _unicode_font(text: str = "") -> Path | None:
    if _has_arabic(text):
        return _first_font(ARABIC_FONTS) or _first_font(BANGLA_FONTS)
    if _has_bengali(text):
        return _first_font(BANGLA_FONTS)
    return _first_font(BANGLA_FONTS) or _first_font(ARABIC_FONTS)


def _is_bold_name(font_name: str) -> bool:
    name = font_name.lower()
    return any(word in name for word in ("bold", "black", "heavy", "semibold", "demi"))


def _is_italic_name(font_name: str) -> bool:
    name = font_name.lower()
    return any(word in name for word in ("italic", "oblique"))


def _builtin_alias(
    font_name: str,
    bold: bool | None = None,
    italic: bool | None = None,
) -> str:
    name = font_name.lower()
    if bold is None:
        bold = _is_bold_name(font_name)
    if italic is None:
        italic = _is_italic_name(font_name)
    if any(word in name for word in ("courier", "mono", "consol", "code")):
        return "cobi" if bold and italic else "cobo" if bold else "coit" if italic else "cour"
    if any(word in name for word in ("times", "serif", "georgia", "garamond", "book")):
        return "tibi" if bold and italic else "tibo" if bold else "tiit" if italic else "tiro"
    return "hebi" if bold and italic else "hebo" if bold else "heit" if italic else "helv"


def _font_supports(path: Path, text: str) -> bool:
    try:
        font = pymupdf.Font(fontfile=str(path))
        return all(font.has_glyph(ord(char)) for char in text if not char.isspace())
    except Exception:
        return False


def _find_embedded(doc: pymupdf.Document, page: pymupdf.Page, font_name: str, text: str) -> Path | None:
    target = _clean(font_name)
    try:
        fonts = page.get_fonts(full=True)
    except Exception:
        return None

    for entry in fonts:
        if not entry:
            continue
        xref = entry[0]
        basefont = entry[3] if len(entry) > 3 else ""
        if not basefont:
            continue
        cleaned = _clean(basefont)
        if cleaned != target and target not in cleaned and cleaned not in target:
            continue
        try:
            _name, ext, _type, buffer = doc.extract_font(xref)
        except Exception:
            continue
        if not buffer or ext not in ("ttf", "otf"):
            continue
        digest = hashlib.sha1(buffer).hexdigest()[:16]
        path = FONT_CACHE / f"{digest}.{ext}"
        if not path.is_file():
            FONT_CACHE.mkdir(parents=True, exist_ok=True)
            path.write_bytes(buffer)
        if _font_supports(path, text):
            return path
    return None


def resolve_font(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    font_name: str,
    text: str,
    bold: bool = False,
    italic: bool = False,
) -> tuple[str, Path | None]:
    if _has_non_latin(text):
        unicode_font = _unicode_font(text)
        if unicode_font:
            return "PDFSUnicode", unicode_font
        return _builtin_alias(font_name, bold=bold, italic=italic), None

    if bold != _is_bold_name(font_name) or italic != _is_italic_name(font_name):
        return _builtin_alias(font_name, bold=bold, italic=italic), None

    embedded = _find_embedded(doc, page, font_name, text)
    if embedded:
        return "PDFSEmbedded", embedded

    return _builtin_alias(font_name, bold=bold, italic=italic), None
