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
| `receipt.png` | OCR path: the receipt number is found in the scanned image and can be edited over it (skipped when Tesseract is missing) |

## Notes

- The Arabic fixture is drawn through `insert_htmlbox` on purpose: `insert_text`
  writes Arabic glyph by glyph without shaping, so it would make a bad fixture.
- Uploaded documents are deleted at the end; use `--keep` to inspect them in the UI.
- Generated fixtures land in `tests/fixtures/` and are git-ignored.
