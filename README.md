# PDF Studio — Local PDF Editor

Edit text, numbers and images **inside** an existing PDF without touching the
background, layout or paper size. Everything runs on your own computer — no
uploads to any server, no account, no cloud.

The app is a small FastAPI backend (PyMuPDF edit engine + Tesseract OCR) that
also serves a pre-built Next.js frontend, so one process on
`http://127.0.0.1:8000` gives you the whole product.

---

## Features

| | |
|---|---|
| **Text editing** | Click a text block, rewrite it. Original font is reused when it can be extracted from the PDF, otherwise a close built-in font is used. |
| **Numbers & dates** | Same as text — good for invoices, totals, ID-style cards, forms. |
| **Images** | Replace an image, add a new one, drag it around, resize with corner handles (Shift keeps the aspect ratio), or delete it. |
| **Erase** | Brush over anything to remove it. For scanned pages a content-aware patch is generated instead of a flat colour box. |
| **OCR** | Scanned PDFs and photos get selectable text. Ships with English + Arabic + Bengali language data. Lone digits and numbers sitting next to a label are kept as their own editable block. |
| **Multi-page** | Page thumbnails, page navigation, per-page undo/redo, export the whole document. |
| **Undo / redo / reset** | Every edit is a JSON operation, so undo is instant and "reset all edits" restores the untouched original. |

Supported inputs: **PDF, PNG, JPG, WEBP, BMP, TIFF** (up to 100 MB per file).

---

## Requirements

- Windows 10/11 (fonts and OCR paths are Windows-specific today)
- Python 3.10+
- Node.js 20.9+ and npm
- Optional: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) —
  install it to `C:\Program Files\Tesseract-OCR` (or set `PDFS_TESSERACT`).
  Language data for `eng`, `ara`, `ben` is already bundled in `data/tessdata`.

---

## Quick start

```bat
start.bat
```

It creates the Python virtual environment, installs dependencies, builds the
frontend the first time, and opens <http://127.0.0.1:8000>.

For development use:

```bat
dev.bat
```

That runs two processes: the API on `:8000` with auto-reload, and Next.js on
`:3000` with hot reload.

### Manual setup

```powershell
py -m venv api\.venv
api\.venv\Scripts\python.exe -m pip install -r api\requirements.txt

cd web
npm install
npm run build
cd ..

api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

> The frontend is a static export (`web/out`). If you change anything under
> `web/src`, run `npm run build` again — the server picks the new files up
> without a restart. Python changes need a server restart.

---

## How it works

```
upload ──► data/uploads/<id>/          source file + document.pdf + meta.json
            │
            ├─ preview ──► /api/documents/{id}/pages/{n}/render   (PyMuPDF PNG)
            │
            ├─ editor  ──► /api/documents/{id}/editor?page=n      spans + images + ops
            │
            └─ edit    ──► PUT /api/documents/{id}/ops            full op list
                              ↳ replay every op on the original PDF
                              ↳ working.pdf + ops.json (atomic replace)
            export ────► /api/documents/{id}/export               working.pdf
```

Every edit is stored as a JSON **operation** instead of mutating the PDF in
place. The server always rebuilds from the original `document.pdf`, so the
result is deterministic and "reset" is just deleting two files.

### Edit operations

| Op | Purpose |
|---|---|
| `add_text` / `replace_text` | Write text at a point, or over a redacted box |
| `delete_text` | Redact a text box |
| `add_image` / `replace_image` / `delete_image` | Place, swap or remove an image |
| `transform_image` | Move / resize an image (collapsed to the final rectangle on rebuild) |
| `erase_area` | Content-aware erase of any rectangle |

### Text rendering notes

- **Latin** text uses the embedded font when it can be extracted, otherwise a
  built-in Helvetica/Times/Courier face.
- **Arabic** (including Arabic-Indic digits) is rendered through MuPDF's HTML
  box, so it is shaped and written right-to-left. On the reading side, a PDF
  stores an Arabic line as several glyph runs in visual order; the editor
  merges those runs into one line, repairs the glyph mapping and shows proper
  logical Arabic, so the whole line is replaced instead of a single fragment.
- **Bengali** currently uses a plain text insertion, which does not shape
  conjuncts correctly. See *Known limitations*.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | App/PyMuPDF version |
| `GET` | `/api/documents?limit=12` | Recent documents |
| `POST` | `/api/documents` | Upload a PDF or image (multipart `file`) |
| `GET` | `/api/documents/{id}` | Document metadata |
| `DELETE` | `/api/documents/{id}` | Delete a document |
| `GET` | `/api/documents/{id}/pages/{n}/render?scale=2` | Render page as PNG |
| `GET` | `/api/documents/{id}/pages/{n}/text` | Raw text spans of a page |
| `GET` | `/api/documents/{id}/editor?page=n` | Editor state (spans, images, ops) |
| `PUT` | `/api/documents/{id}/ops` | Replace the op list and rebuild |
| `POST` | `/api/documents/{id}/reset` | Drop all edits |
| `GET` | `/api/documents/{id}/export` | Download the edited PDF |
| `POST` | `/api/assets` | Upload an image asset used by ops |

Interactive API docs: <http://127.0.0.1:8000/docs>

---

## Project layout

```
api/
  main.py            FastAPI app, CORS, static mount of web/out
  core/
    config.py        paths and limits
    storage.py       upload / metadata / list / delete
    pdf_engine.py    inspect, render, span extraction, image→PDF
    editor.py        op executor, rebuild, editor state, OCR merge
    fonts.py         embedded-font lookup and built-in fallbacks
    ocr.py           Tesseract pipeline with on-disk cache
    assets.py        image asset store
  routers/           HTTP endpoints
web/
  src/app/           home page, /editor page, layout, styles
  src/components/    workspace, dropzone, preview, editor, page canvas
  src/lib/           typed API clients
data/
  uploads/<id>/      one folder per document (private, git-ignored)
  assets/            uploaded images (private, git-ignored)
  tessdata/          OCR language data (eng, ara, ben)
tests/               neutral fixtures + end-to-end smoke test
start.bat / dev.bat  one-click run scripts
```

---

## Configuration

| Variable | Effect |
|---|---|
| `PDFS_TESSERACT` | Full path to `tesseract.exe` |
| `PDFS_OCR_LANGS` | Override OCR languages, e.g. `eng+ara` |
| `NEXT_PUBLIC_API_BASE` | Frontend API origin (only needed for custom hosting) |

---

## Development checks

```powershell
cd web
npx tsc --noEmit     # types
npm run lint         # eslint
npm run build        # static export into web/out
```

End-to-end smoke test (neutral generated documents, no user data):

```powershell
api\.venv\Scripts\python.exe tests\make_fixtures.py
api\.venv\Scripts\python.exe tests\smoke_test.py
```

It covers vector text, numbers, the OCR path and Arabic line handling. See
`tests/README.md`.

---

## Privacy

- The server binds to `127.0.0.1` only.
- Files never leave the machine; there is no telemetry.
- Uploaded files, image assets, OCR caches and font caches live under `data/`
  and are git-ignored, so a clone never contains somebody's documents.

---

## Known limitations

- **Bengali shaping**: conjuncts are not re-ordered; exported text is correct
  but the glyphs look wrong. Fix is to route Bengali through the HTML box like
  Arabic.
- **Arabic text layer**: an Arabic line written by the editor is stored by
  MuPDF in visual glyph order, so copying or searching it in another PDF reader
  can return the letters in reverse. The editor itself reads it back correctly.
- **Font fidelity**: if the original font cannot be extracted from the PDF, a
  built-in face is substituted, so replaced text may look slightly different.
  There is no font picker in the UI yet.
- **Redo**: only one step of redo works — the stack is cleared after a rebuild.
- **Rebuild cost**: every change replays all operations on the original file;
  many edits on a large PDF get slower (500 operations is the hard cap).
- **OCR**: only runs for pages without a text layer; first run can take
  several seconds and shows no progress bar.
- **Housekeeping**: deleting a document does not clean up its image assets or
  OCR cache.
- **Single line text**: no paragraph/justification support yet.

---

## License

Private project — all rights reserved.
