import re

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, HTMLResponse
from pydantic import BaseModel

import fitz
from extractor import pdf_to_html
from debug_extract import raw_page_html
from converter import to_html, to_docx, to_epub

app = FastAPI(title="PDF HTML Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Extract ───────────────────────────────────────────────────────────────────

@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        doc         = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        doc.close()
        html = pdf_to_html(pdf_bytes)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {exc}")

    return JSONResponse({"html": html, "pages": total_pages})


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Download ──────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    html:   str
    title:  str = "Extracted Book"
    author: str = "Unknown"


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:80] or "book"


@app.post("/download/html")
async def download_html(req: DownloadRequest):
    data = to_html(req.html, req.title)
    return Response(
        content=data,
        media_type="text/html",
        headers={"Content-Disposition":
                 f'attachment; filename="{_safe_filename(req.title)}.html"'},
    )


@app.post("/download/docx")
async def download_docx(req: DownloadRequest):
    try:
        data = to_docx(req.html, req.title)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DOCX conversion failed: {exc}")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument"
                   ".wordprocessingml.document",
        headers={"Content-Disposition":
                 f'attachment; filename="{_safe_filename(req.title)}.docx"'},
    )


@app.post("/download/epub")
async def download_epub(req: DownloadRequest):
    try:
        data = to_epub(req.html, req.title, req.author)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"EPUB conversion failed: {exc}")
    return Response(
        content=data,
        media_type="application/epub+zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{_safe_filename(req.title)}.epub"'},
    )


# ── Debug ─────────────────────────────────────────────────────────────────────

@app.post("/debug")
async def debug_pdf(file: UploadFile = File(...), page: int = 0):
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        debug_html = raw_page_html(pdf_bytes, page)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return HTMLResponse(content=debug_html)
