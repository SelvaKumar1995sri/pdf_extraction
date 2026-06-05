---
name: pdf-html-extractor
description: >
  Build or extend the PDF-to-HTML split-panel web application in this project.
  Use this skill whenever the user wants to: add a feature to the PDF viewer or HTML preview,
  fix a bug in the extraction pipeline, change how fonts/images/styles are extracted,
  adjust the split-panel layout, wire up a new API endpoint, or scaffold the project
  from scratch. If the user mentions PDF, extraction, split view, HTML preview, or the
  backend parser, invoke this skill before doing anything else.
---

## Project Overview

This is a **split-panel PDF extraction web app**:

- **Left panel** — embedded PDF viewer showing the original file (using `<iframe>` or pdf.js)
- **Right panel** — live HTML preview of the extracted content, preserving text styles (bold, italic, size, color), font families, layout structure, and embedded images
- **Backend** — Python server (Flask or FastAPI) that receives the uploaded PDF, parses it, and returns structured HTML

The goal is pixel-faithful HTML reconstruction: the right panel should feel like a styled re-rendering of the PDF, not a plain text dump.

---

## Architecture

```
[Browser]
  ├── File input  ──upload──►  POST /extract  ──►  [Python Backend]
  ├── Left panel  ◄──blob URL──  same file               │
  └── Right panel ◄────────────── HTML string ◄──────────┘

[Python Backend]
  ├── PDF parser: pdfplumber (text + layout) + PyMuPDF/fitz (images + fonts)
  ├── HTML builder: assembles spans/divs with inline styles
  └── Image handler: extracts images, base64-encodes them for embedding
```

---

## Backend (Python)

### Recommended stack
- **FastAPI** (preferred for async) or **Flask**
- **pdfplumber** — precise text extraction with character-level bounding boxes, font size, font name
- **PyMuPDF (fitz)** — image extraction per page, also provides font color and weight data
- **Pillow** — image format conversion if needed
- **python-multipart** — file upload handling (FastAPI)

### Image filter rule (editable pages)
Show an image block **only if** its bbox does NOT overlap any text block by more than 5 %.  
Do NOT apply a size filter — genuine illustrations (lighthouse ~17 % of page) must pass.  
Background overlays are caught by the overlap check because they always sit on top of text.

## Right-panel goal
The extracted HTML is **editable** (`contenteditable="true"`).  
Use **flow layout** (not absolute positioning) so users can click text and type.  
Each text line → `<div style="text-align:…">` + `<span>` children with font/size/color.  
Images → `<img contenteditable="false">` centred in a div, rendered via `page.get_pixmap(clip=rect)`.  
Do NOT use `position:absolute` or CSS transforms on the content — they break editing.

## Key extraction logic

**Text with styles** — use `pdfplumber` page chars:
```python
for char in page.chars:
    # char keys: text, fontname, size, stroking_color, non_stroking_color, x0, y0, x1, y1
    style = build_inline_style(char)  # font-size, font-family, color, bold/italic detection
    spans.append(f'<span style="{style}">{char["text"]}</span>')
```

**Bold/italic detection** — infer from `fontname` string:
```python
def font_flags(fontname: str) -> tuple[bool, bool]:
    name = fontname.lower()
    bold = "bold" in name or "bd" in name or ",b" in name
    italic = "italic" in name or "oblique" in name or ",i" in name
    return bold, italic
```

**Images** — extract via PyMuPDF and embed as base64:
```python
doc = fitz.open(stream=pdf_bytes, filetype="pdf")
for page in doc:
    for img_info in page.get_images():
        xref = img_info[0]
        base_image = doc.extract_image(xref)
        b64 = base64.b64encode(base_image["image"]).decode()
        mime = base_image["ext"]  # e.g. "png", "jpeg"
        img_tags.append(f'<img src="data:{mime};base64,{b64}" style="max-width:100%"/>')
```

**Page structure** — wrap each page in a `<div class="pdf-page">` with a top-level `position:relative` container so text and images can be positioned if needed.

### API endpoint

```
POST /extract
  Content-Type: multipart/form-data
  Body: file=<pdf binary>

Response 200:
  { "html": "<div class='pdf-page'>...</div><div class='pdf-page'>...</div>" }

Response 400:
  { "error": "Invalid or unreadable PDF" }
```

Enable CORS so the frontend (served separately during dev) can call this endpoint.

---

## Frontend (HTML/CSS/JS)

### Layout

```
┌──────────────────────────────────────────┐
│  [Choose PDF]  [Upload button]           │
├─────────────────┬────────────────────────┤
│                 │                        │
│   PDF VIEWER    │    HTML PREVIEW        │
│   (left 50%)    │    (right 50%)         │
│   <iframe> or   │    innerHTML =         │
│   pdf.js canvas │    response.html       │
│                 │                        │
└─────────────────┴────────────────────────┘
```

- Use CSS `display:flex` on a `.container` div; each panel is `width:50%; overflow-y:auto; height:calc(100vh - header)`
- A vertical **resizable divider** (drag to resize) is a nice-to-have; use CSS `resize` or a JS drag listener

### PDF viewer (left panel)

Simplest: create an object URL from the uploaded `File` and set it as the `src` of an `<iframe>`:
```js
const url = URL.createObjectURL(file);
pdfFrame.src = url;
```
If the browser blocks iframe PDFs (Chrome sometimes does), fall back to embedding via pdf.js.

### HTML preview (right panel)

```js
const formData = new FormData();
formData.append("file", file);
const res = await fetch("/extract", { method: "POST", body: formData });
const { html } = await res.json();
previewPane.innerHTML = html;
```

Add a loading spinner while the request is in flight.

### Styling the preview pane

The right panel should have a white background and its own scroll. Extracted HTML uses inline styles so it does not need extra CSS, but reset any inherited styles so the host page CSS doesn't bleed in:
```css
.preview-pane { all: initial; display: block; ... }
```
Or wrap extracted content in a shadow DOM for true isolation.

---

## File layout to build

```
project/
├── backend/
│   ├── main.py          # FastAPI app, /extract endpoint
│   ├── extractor.py     # PDF → HTML logic
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

---

## Common pitfalls to avoid

| Problem | Fix |
|---|---|
| Characters render out of order | Sort `page.chars` by `(y0, x0)` before grouping into lines |
| Merged characters (no spaces) | Group chars into words by checking x-gap between consecutive chars |
| Images appear before text | Collect images separately, append after text block per page |
| Font size mismatch | `char["size"]` is in PDF points; use as `font-size: Xpt` directly |
| CORS error in dev | Add `allow_origins=["*"]` in FastAPI or `CORS(app)` in Flask |
| PDF not rendering in iframe | Use `<embed>` with `type="application/pdf"` as fallback |

---

## When adding a feature

1. Identify which layer it belongs to: extraction logic (`extractor.py`), API (`main.py`), or UI (`app.js` / `style.css`)
2. Make the backend change first, test the `/extract` endpoint with `curl` or a REST client
3. Update the frontend to consume the new data
4. Check that both panels still scroll independently and the layout doesn't break on narrow screens
