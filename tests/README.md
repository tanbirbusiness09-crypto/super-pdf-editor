# Smoke tests

Neutral, generated documents plus an end-to-end check of the running app.
Nothing here touches real user files.

```powershell
# 1) generate fixtures (invoice.pdf, receipt.png, arabic-letter.pdf)
api\.venv\Scripts\python.exe tests\make_fixtures.py

# 2) start the app once (start.bat) and run the checks
api\.venv\Scripts\python.exe tests\smoke_test.py
```

Options: `--base http://127.0.0.1:8000`, `--fixtures <dir>`, `--keep`.
Exit code `0` = all checks passed, `1` = something failed, `2` = fixtures missing.

## What is covered

| Fixture | Path being tested |
|---|---|
| `invoice.pdf` | Vector text: numbers are extracted, replaced, and the exported PDF contains the new values |
| `arabic-letter.pdf` | RTL handling: glyph fragments are merged into one logical line, Arabic-Indic digits keep their order, no presentation-form characters leak into the editor, the edited line replaces the old one |
| `short-spans.pdf` | One-character (`7`) and single-word (`TOTAL`) spans can be selected and edited |
| `short-ocr.png` | OCR: a lone digit becomes a span, a number next to a label (`TOTAL 7`) is split into its own block and can be edited |
| `fit-check.pdf` | Long replacements never shrink below 75% of the requested size (no invisible 3pt text) |
| `receipt.png` | OCR path: the receipt number is found in the scanned image and can be edited over it (skipped when Tesseract is missing) |

## Notes

- The Arabic fixture is drawn through `insert_htmlbox` on purpose: `insert_text`
  writes Arabic glyph by glyph without shaping, so it would make a bad fixture.
- Uploaded documents are deleted at the end; use `--keep` to inspect them in the UI.
- Generated fixtures land in `tests/fixtures/` and are git-ignored.
