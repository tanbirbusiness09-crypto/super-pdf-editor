"""Generate neutral fixtures for the smoke test.

Everything here is invented content (an English invoice, a payment receipt
image and an Arabic/English letter) so the editor can be checked without any
personal or real-world document.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

ARABIC_NAME = "السيد محمد أحمد"
ARABIC_DATE = "٢٦/١٢/٢٠٢٧"

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build_invoice(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=440, height=300)
    page.insert_text((40, 70), "INVOICE", fontsize=18)
    page.insert_text((40, 120), "Invoice no: 7823419", fontsize=13)
    page.insert_text((40, 150), "Total: 1,250.00 AED", fontsize=13)
    page.insert_text((40, 180), "VAT: 62.50", fontsize=13)
    page.insert_text((40, 220), "Payment terms: 30 days", fontsize=13)
    doc.save(path)
    doc.close()


def build_receipt(path: Path) -> None:
    image = Image.new("RGB", (900, 380), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 50), "PAYMENT RECEIPT", fill="black", font=_font(34))
    draw.text((60, 140), "Receipt no: 5530012", fill="black", font=_font(26))
    draw.text((60, 200), "Amount paid: 4,850.00", fill="black", font=_font(26))
    draw.text((60, 260), "Date: 14/03/2026", fill="black", font=_font(26))
    image.save(path)


def build_arabic_letter(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=520, height=340)
    page.insert_text((40, 60), "ARABIC / ENGLISH TEST DOCUMENT", fontsize=12)
    page.insert_text((40, 110), "Customer name:  ALI HASSAN MOHAMED", fontsize=12)
    page.insert_text((40, 150), "Reference:  7823419", fontsize=12)
    page.insert_text((40, 190), "Date:  26/12/2026", fontsize=12)
    # Arabic has to be drawn through the HTML box, otherwise the glyphs are
    # written one by one without shaping.
    page.insert_htmlbox(
        pymupdf.Rect(300, 250, 505, 290),
        f'<div style="direction:rtl;text-align:right;font-size:14px;line-height:1.2;">{ARABIC_NAME}</div>',
    )
    page.insert_htmlbox(
        pymupdf.Rect(300, 295, 505, 332),
        f'<div style="direction:rtl;text-align:right;font-size:14px;line-height:1.2;">{ARABIC_DATE}</div>',
    )
    doc.save(path)
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "fixtures",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    build_invoice(args.out / "invoice.pdf")
    build_receipt(args.out / "receipt.png")
    build_arabic_letter(args.out / "arabic-letter.pdf")
    for name in ("invoice.pdf", "receipt.png", "arabic-letter.pdf"):
        print(f"wrote {args.out / name}")


if __name__ == "__main__":
    main()
