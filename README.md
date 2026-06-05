# PDF Content Extractor

A split-panel web application that displays a PDF on the left and its fully extracted, editable HTML content on the right — with images, fonts, alignment, and styling faithfully reproduced.

---

## Features

- **Split-panel view** — Original PDF on the left, extracted HTML on the right
- **Editable content** — All extracted text is `contenteditable`; click any paragraph to edit it
- **Faithful text extraction** — Font size, weight, italic, and colour are preserved per span
- **PUA font fix** — Custom display fonts (e.g. GambadoSans) that store glyphs at `ASCII + 18` are automatically decoded to correct Unicode characters
- **Alignment detection** — Centred and right-aligned paragraphs are detected from bounding-box analysis and rendered with matching `text-align` CSS
- **Image extraction** — Inline images (illustrations, logos) are rendered from the page via PyMuPDF and embedded as base64 PNG
- **A4 pages** — Every extracted page is at least A4 size (794 × 1123 px) with a white paper background
- **Embedded fonts** — `@font-face` CSS from PyMuPDF is injected at the document level so custom PDF fonts render in the browser
- **Sync scrollbar** — A centre scrollbar + mouse-wheel sync scroll both panels simultaneously for easy comparison
- **Resizable divider** — Drag the divider between panels to adjust the split

---

## Project Structure

```
Pdf content extraction/
├── backend/
│   ├── main.py           # FastAPI server — POST /extract, GET /health
│   ├── extractor.py      # PDF → HTML conversion logic (PyMuPDF)
│   └── requirements.txt  # Python dependencies
├── frontend/
│   ├── index.html        # App shell (split-panel layout)
│   ├── style.css         # Dark toolbar + panel styles + sync scrollbar
│   └── app.js            # File picker, extract call, sync scroll, divider resize
└── README.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 + |
| pip | any recent |
| Modern browser | Chrome 110 + / Edge 110 + (for PDF `<iframe>` + `@font-face`) |

---

## Installation

### 1. Clone / download the project

```bash
git clone <repo-url>
cd "Pdf content extraction"
```

### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

Dependencies installed:

| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn[standard]` | ASGI server |
| `PyMuPDF` | PDF parsing, text/image extraction, page rendering |
| `Pillow` | Image colour-space conversion (CMYK → RGB, SMask handling) |
| `python-multipart` | File upload support for FastAPI |

---

## Running the App

### 1. Start the backend server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 2. Open the frontend

Open `frontend/index.html` directly in your browser:

```
File → D:\...\frontend\index.html
```

> The frontend is plain HTML/CSS/JS — no build step needed. Just open the file.

---

## Using the App

### Step 1 — Choose a PDF

Click **Choose PDF** in the toolbar and select any `.pdf` file.  
The PDF appears immediately in the left panel.

### Step 2 — Extract

Click **Extract**.  
The backend parses the PDF and returns styled HTML.  
When complete, the right panel shows the extracted content page by page.

### Step 3 — Compare & Edit

| Action | Result |
|---|---|
| **Drag the centre scrollbar** | Scrolls both panels simultaneously |
| **Mouse wheel over either panel** | Scrolls both panels |
| **Click any text in the right panel** | Places cursor — text is fully editable |
| **Drag the divider** | Resizes the left/right split |

---

## API Reference

### `POST /extract`

Extracts a PDF and returns styled HTML.

**Request:** `multipart/form-data` with field `file` (`.pdf` binary)

**Response:**
```json
{
  "html": "<style>@font-face{...}</style><div contenteditable=\"true\">...</div>...",
  "pages": 224
}
```

**Error responses:**

| Status | Meaning |
|---|---|
| `400` | File is not a PDF or is empty |
| `422` | PDF could not be parsed |

### `GET /health`

Returns `{"status": "ok"}` — used to verify the server is running.

---

## How Extraction Works

```
PDF file
  │
  ├─ get_text("dict")  ──► text blocks → flow HTML
  │   ├─ alignment detection (centre / right / left from bbox)
  │   ├─ PUA fix: U+E000+ASCII+18 → subtract 0xE012 → correct char
  │   └─ font flags (bold/italic from font name)
  │
  ├─ get_text("html")  ──► @font-face CSS harvested, deduplicated
  │                         injected once at document level
  │
  ├─ image blocks      ──► rendered via get_pixmap(clip=rect)
  │   ├─ size filter  (≥ 12 pt each side)
  │   ├─ aspect ratio (≤ 4 : 1)
  │   ├─ height guard (rendered PNG ≤ 600 px)
  │   └─ overlap filter (skip if bbox overlaps text blocks)
  │
  └─ cover/art pages   ──► full-page PNG render (when < 120 chars
                            and images cover > 35 % of page area)
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **CORS error in browser console** | Make sure the backend is running on port 8000 |
| **"Could not parse PDF"** | The PDF may be password-protected or corrupted |
| **Boxes (□) in headings** | The PDF uses a non-standard font encoding not covered by the PUA fix. The `@font-face` embedding should handle it; if not, report the font name |
| **Images missing** | Images smaller than 12 pt, with extreme aspect ratios, or overlapping body text are filtered. Adjust thresholds in `extractor.py` |
| **Extraction is slow** | Large PDFs (200 + pages) take 30–90 s. Each page calls `get_text("html")` once to harvest fonts, plus `get_pixmap` for each inline image |
| **PDF not showing in left panel** | Some browsers block local `blob:` URLs in iframes. Try Chrome or Edge |

---

## Configuration

Key constants at the top of `backend/extractor.py`:

| Constant | Default | Description |
|---|---|---|
| `RENDER_WIDTH` | `794` | Page width in px (A4 at 96 DPI) |
| `A4_MIN_H` | `1123` | Minimum page height in px (A4 at 96 DPI) |
| `MIN_IMG_PT` | `4` | Minimum image dimension to attempt rendering (pt) |
| `MULTI_IMG_ZOOM` | `1.5` | Zoom factor for full-page cover renders |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, FastAPI, PyMuPDF, Pillow |
| Frontend | Vanilla HTML / CSS / JavaScript (no framework) |
| PDF rendering | Browser built-in PDF viewer (iframe) |
| Fonts | PyMuPDF `@font-face` embedding + PUA decode |

---

## License

This project is for internal / educational use.
