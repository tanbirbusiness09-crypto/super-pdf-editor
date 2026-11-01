"""End-to-end smoke test for PDF Studio.

Runs against a live API (default http://127.0.0.1:8000), uploads the neutral
fixtures from ``make_fixtures.py``, edits them through the same endpoints the
web UI uses, and checks the result.

    python tests/smoke_test.py            # generate fixtures if missing, then test
    python tests/smoke_test.py --keep     # keep the uploaded documents

Exit code 0 means every check passed. OCR checks are skipped (not failed) when
Tesseract is not installed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api_client import Api

DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARABIC_NAME = "السيد محمد أحمد"
ARABIC_DATE = "٢٦/١٢/٢٠٢٧"
ARABIC_NAME_NEW = "السيد خالد سعيد"
ARABIC_DATE_NEW = "١٤/٠٣/٢٠٢٧"
PRESENTATION_FORMS = range(0xFB50, 0xFEFF)


class Checker:
    def __init__(self) -> None:
        self.failures = 0
        self.skips = 0

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            print(f"PASS  {name}")
        else:
            self.failures += 1
            print(f"FAIL  {name}" + (f"  ({detail})" if detail else ""))
        return bool(condition)

    def skip(self, name: str, reason: str) -> None:
        self.skips += 1
        print(f"SKIP  {name}  ({reason})")


def normalized(text: str) -> str:
    return " ".join(text.split())


def has_presentation_forms(text: str) -> bool:
    return any(ord(char) in PRESENTATION_FORMS for char in text)


def find_span(spans: list[dict], needle: str) -> dict | None:
    for span in spans:
        if needle in span.get("text", ""):
            return span
    return None


def replace_op(span: dict, text: str) -> dict:
    return {
        "type": "replace_text",
        "page": 0,
        "bbox": span["bbox"],
        "origin": span["origin"],
        "text": text,
        "font": span.get("font") or "Helvetica",
        "size": span["size"],
        "color": span.get("color") or "#111111",
        "bold": False,
        "fit": False,
    }


def ocr_replace_op(span: dict, text: str) -> list[dict]:
    pad = 1.5
    x0, y0, x1, y1 = span["bbox"]
    return [
        {
            "type": "erase_area",
            "page": 0,
            "rect": [x0 - pad, y0 - pad, x1 + pad, y1 + pad],
        },
        {
            "type": "add_text",
            "page": 0,
            "origin": [x0, y1 - span["size"] * 0.18],
            "bbox": span["bbox"],
            "text": text,
            "font": "Helvetica",
            "size": span["size"],
            "color": span.get("color") or "#111111",
            "bold": False,
            "fit": False,
        },
    ]


def check_invoice(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "invoice.pdf")
    try:
        spans = api.editor(meta["id"])["spans"]
        checks.check(
            "invoice: numbers are extracted as text",
            find_span(spans, "7823419") is not None,
            f"spans={[s['text'] for s in spans]}",
        )

        invoice_no = find_span(spans, "Invoice no: 7823419")
        total = find_span(spans, "Total: 1,250.00 AED")
        if not invoice_no or not total:
            checks.check("invoice: expected spans exist", False)
            return

        api.put_ops(
            meta["id"],
            [
                replace_op(invoice_no, "Invoice no: 9911223"),
                replace_op(total, "Total: 9,999.00 AED"),
            ],
        )

        after = api.editor(meta["id"])["spans"]
        checks.check(
            "invoice: new invoice number is applied",
            find_span(after, "9911223") is not None,
        )
        checks.check(
            "invoice: new total is applied",
            find_span(after, "9,999.00 AED") is not None,
        )

        exported = api.export_text(meta["id"])
        checks.check(
            "invoice: export contains the edited numbers",
            "9911223" in exported and "9,999.00" in exported,
            exported[:120],
        )
    finally:
        api.delete(meta["id"])


def check_arabic(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "arabic-letter.pdf")
    try:
        spans = api.editor(meta["id"])["spans"]
        rtl = [span for span in spans if span.get("rtl")]
        checks.check("arabic: line is flagged rtl", len(rtl) >= 2, f"rtl={len(rtl)}")

        name_span = next(
            (span for span in rtl if normalized(span["text"]) == ARABIC_NAME), None
        )
        checks.check(
            "arabic: fragments are merged into one logical line",
            name_span is not None,
            f"got={[s['text'] for s in rtl]}",
        )
        date_span = next(
            (span for span in rtl if normalized(span["text"]) == ARABIC_DATE), None
        )
        checks.check(
            "arabic: arabic-indic digits keep their order",
            date_span is not None,
            f"got={[s['text'] for s in rtl]}",
        )
        checks.check(
            "arabic: no presentation-form glyph leaks into the editor",
            not any(has_presentation_forms(span["text"]) for span in spans),
        )

        if not name_span or not date_span:
            return

        api.put_ops(
            meta["id"],
            [
                replace_op(name_span, ARABIC_NAME_NEW),
                replace_op(date_span, ARABIC_DATE_NEW),
            ],
        )
        after = api.editor(meta["id"])["spans"]
        checks.check(
            "arabic: edited line replaces the old one",
            find_span(after, ARABIC_NAME_NEW) is not None
            and find_span(after, ARABIC_NAME) is None,
        )
        checks.check(
            "arabic: edited date replaces the old one",
            find_span(after, ARABIC_DATE_NEW) is not None
            and find_span(after, ARABIC_DATE) is None,
        )

        png = api.render(meta["id"])
        checks.check(
            "arabic: page still renders as PNG",
            png.startswith(b"\x89PNG") and len(png) > 2000,
            f"bytes={len(png)}",
        )
    finally:
        api.delete(meta["id"])


def drawn_size(api: Api, doc_id: str, needle: str) -> float | None:
    """Size the text was actually written with inside the exported PDF."""
    import pymupdf

    data = api.export(doc_id)
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for block in doc[0].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if needle in span["text"]:
                        return round(float(span["size"]), 2)
    return None


def check_short_vector(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "short-spans.pdf")
    try:
        spans = api.editor(meta["id"])["spans"]
        texts = [normalized(span["text"]) for span in spans]
        checks.check(
            "short vector: one-character span is offered",
            "7" in texts,
            f"spans={texts}",
        )
        checks.check(
            "short vector: single-word span is offered",
            "TOTAL" in texts,
            f"spans={texts}",
        )

        digit = next((s for s in spans if normalized(s["text"]) == "7"), None)
        word = next((s for s in spans if normalized(s["text"]) == "TOTAL"), None)
        if not digit or not word:
            return

        api.put_ops(meta["id"], [replace_op(digit, "9"), replace_op(word, "GRAND")])
        after = [normalized(span["text"]) for span in api.editor(meta["id"])["spans"]]
        checks.check(
            "short vector: one-character edit is applied",
            "9" in after and "7" not in after,
            f"spans={after}",
        )
        checks.check(
            "short vector: single-word edit is applied",
            "GRAND" in after and "TOTAL" not in after,
            f"spans={after}",
        )
    finally:
        api.delete(meta["id"])


def check_short_ocr(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "short-ocr.png")
    try:
        spans = api.editor(meta["id"])["spans"]
        if not any(span.get("ocr") for span in spans):
            checks.skip("short ocr: editable short spans", "no OCR text")
            return

        texts = [normalized(span["text"]) for span in spans]
        checks.check(
            "short ocr: lone digit is detected",
            "5" in texts,
            f"spans={texts}",
        )
        checks.check(
            "short ocr: number is split away from its label",
            "TOTAL" in texts and "7" in texts,
            f"spans={texts}",
        )

        target = next((s for s in spans if normalized(s["text"]) == "7"), None)
        if not target:
            return

        api.put_ops(meta["id"], ocr_replace_op(target, "9"))
        after = [normalized(span["text"]) for span in api.editor(meta["id"])["spans"]]
        checks.check(
            "short ocr: number edit is applied",
            "9" in after and "TOTAL" in after,
            f"spans={after}",
        )
    finally:
        api.delete(meta["id"])


def check_fit_floor(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "fit-check.pdf")
    try:
        spans = api.editor(meta["id"])["spans"]
        target = next((s for s in spans if normalized(s["text"]) == "W"), None)
        if not checks.check("fit: single-letter box exists", target is not None):
            return

        api.put_ops(meta["id"], [replace_op(target, "WIDE REPLACEMENT TEXT")])
        size = drawn_size(api, meta["id"], "WIDE")
        checks.check(
            "fit: long text keeps a readable size instead of shrinking to 3pt",
            size is not None and size >= round(target["size"] * 0.74, 2),
            f"drawn={size} original={target['size']}",
        )
    finally:
        api.delete(meta["id"])


def check_receipt(api: Api, checks: Checker, fixtures: Path) -> None:
    meta = api.upload(fixtures / "receipt.png")
    try:
        spans = api.editor(meta["id"])["spans"]
        ocr_spans = [span for span in spans if span.get("ocr")]
        if not ocr_spans:
            checks.skip(
                "receipt: ocr number edit",
                "no OCR text (is Tesseract installed?)",
            )
            return

        target = find_span(ocr_spans, "5530012")
        if not checks.check(
            "receipt: ocr found the receipt number",
            target is not None,
            f"spans={[s['text'] for s in ocr_spans]}",
        ):
            return

        api.put_ops(meta["id"], ocr_replace_op(target, "7719984"))
        after = api.editor(meta["id"])["spans"]
        checks.check(
            "receipt: edited number is applied over the image",
            find_span(after, "7719984") is not None,
        )
    finally:
        api.delete(meta["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--keep", action="store_true", help="keep uploaded documents")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    fixtures = args.fixtures
    if not (fixtures / "invoice.pdf").is_file():
        print(f"fixtures missing in {fixtures} — run make_fixtures.py first")
        return 2

    api = Api(args.base, keep=args.keep)
    checks = Checker()

    if not checks.check("api: health endpoint answers", api.health()):
        return 1

    check_invoice(api, checks, fixtures)
    check_arabic(api, checks, fixtures)
    check_short_vector(api, checks, fixtures)
    check_short_ocr(api, checks, fixtures)
    check_fit_floor(api, checks, fixtures)
    check_receipt(api, checks, fixtures)

    print(
        f"\n{checks.failures} failed, {checks.skips} skipped, "
        f"fixtures: {fixtures}"
    )
    return 1 if checks.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
