"""
debug_extract.py — raw PyMuPDF extraction viewer.

Endpoint:  POST /debug?page=0
Returns a human-readable HTML page showing the exact blocks/lines/spans
that PyMuPDF produces for a given PDF page, with ZERO post-processing.
"""

import html
import io
import fitz


def raw_page_html(pdf_bytes: bytes, page_index: int) -> str:
    """Return a self-contained debug HTML page for one PDF page."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = len(doc)
    page_index = max(0, min(page_index, total - 1))
    page = doc[page_index]

    pw_pt = page.rect.width
    ph_pt = page.rect.height

    # ── Raw dict extraction ───────────────────────────────────────────────
    flags = (fitz.TEXT_PRESERVE_WHITESPACE
             | fitz.TEXT_MEDIABOX_CLIP
             | fitz.TEXT_PRESERVE_IMAGES)
    raw = page.get_text("dict", flags=flags)
    blocks = raw["blocks"]

    # ── Plain text extraction ─────────────────────────────────────────────
    plain_text = page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    # ── Build HTML ────────────────────────────────────────────────────────
    rows = []

    for bi, blk in enumerate(blocks):
        btype = blk.get("type", "?")
        bx0, by0, bx1, by1 = blk["bbox"]
        blk_area = (bx1-bx0)*(by1-by0)
        page_area = pw_pt * ph_pt
        pct = blk_area / page_area * 100 if page_area else 0

        if btype == 0:   # text block
            rows.append(f"""
<details open>
  <summary class="blk-hdr blk-text">
    BLOCK {bi} · TEXT · bbox=({bx0:.1f},{by0:.1f},{bx1:.1f},{by1:.1f})
    · area={pct:.1f}% · lines={len(blk.get('lines',[]))}
  </summary>
  <div class="blk-body">""")

            for li, ln in enumerate(blk.get("lines", [])):
                lx0, ly0, lx1, ly1 = ln["bbox"]
                gap_above = ""
                if li > 0:
                    prev_bottom = blk["lines"][li-1]["bbox"][3]
                    gap = ly0 - prev_bottom
                    gap_above = f'<span class="gap">gap={gap:.1f}pt</span>'

                rows.append(f"""
    <details open>
      <summary class="ln-hdr">LINE {li} {gap_above}
        · bbox=({lx0:.1f},{ly0:.1f},{lx1:.1f},{ly1:.1f})</summary>
      <table class="span-tbl">
        <thead><tr>
          <th>#</th><th>text</th><th>font</th>
          <th>size</th><th>color</th><th>bold?</th><th>italic?</th>
          <th>bbox</th>
        </tr></thead><tbody>""")

                for si, sp in enumerate(ln.get("spans", [])):
                    raw_text  = sp["text"]
                    safe_text = html.escape(raw_text)
                    font      = sp["font"]
                    size      = sp["size"]
                    color_int = sp["color"]
                    r = (color_int >> 16) & 0xFF
                    g = (color_int >>  8) & 0xFF
                    b = color_int & 0xFF
                    sx0, sy0, sx1, sy1 = sp["bbox"]
                    n = font.lower()
                    is_bold   = any(k in n for k in ["bold","demi","heavy",",b","-bd"])
                    is_italic = any(k in n for k in ["italic","oblique",",i"])

                    # Show PUA chars
                    pua_chars = [hex(ord(c)) for c in raw_text
                                 if 0xE000 <= ord(c) <= 0xF8FF]
                    pua_note  = f'<br><span class="pua">PUA: {", ".join(pua_chars)}</span>' \
                                if pua_chars else ""

                    rows.append(f"""
          <tr>
            <td>{si}</td>
            <td class="cell-text">{safe_text}{pua_note}</td>
            <td class="cell-font">{html.escape(font)}</td>
            <td>{size:.1f}pt</td>
            <td><span class="swatch" style="background:rgb({r},{g},{b})"></span>
                rgb({r},{g},{b})</td>
            <td>{'✓' if is_bold else ''}</td>
            <td>{'✓' if is_italic else ''}</td>
            <td style="font-size:0.7em">{sx0:.0f},{sy0:.0f},{sx1:.0f},{sy1:.0f}</td>
          </tr>""")

                rows.append("      </tbody></table></details>")

            rows.append("  </div></details>")

        elif btype == 1:   # image block
            iw = bx1 - bx0
            ih = by1 - by0
            ext = blk.get("ext", "?")
            img_bytes = blk.get("image", b"")
            rows.append(f"""
<details>
  <summary class="blk-hdr blk-img">
    BLOCK {bi} · IMAGE · bbox=({bx0:.1f},{by0:.1f},{bx1:.1f},{by1:.1f})
    · size={iw:.0f}×{ih:.0f}pt · ext={ext} · data={len(img_bytes)} bytes
    · area={pct:.1f}%
  </summary>
  <div class="blk-body">
    <p class="img-note">Image data present: {bool(img_bytes)}</p>
  </div>
</details>""")

    doc.close()

    # Also list images from get_images()
    doc2 = fitz.open(stream=pdf_bytes, filetype="pdf")
    page2 = doc2[page_index]
    img_list = page2.get_images(full=True)
    img_rows = ""
    for ii, info in enumerate(img_list):
        xref, smask, w, h, bpc, cs, _, name, filt, enc = (info + (None,)*10)[:10]
        try:
            rects = page2.get_image_rects(xref)
            rect_str = " | ".join(f"({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f})"
                                  for r in rects)
        except Exception:
            rect_str = "N/A"
        img_rows += (f"<tr><td>{ii}</td><td>{xref}</td><td>{w}×{h}</td>"
                     f"<td>{cs}</td><td>{filt}</td>"
                     f"<td style='font-size:0.75em'>{rect_str}</td></tr>")
    doc2.close()

    blocks_json = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>RAW EXTRACTION — page {page_index+1}/{total}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; font-size: 13px;
         background:#1e1e2e; color:#cdd6f4; margin:0; padding:0; }}
  .topbar {{ background:#181825; padding:10px 20px; display:flex;
             align-items:center; gap:16px; border-bottom:1px solid #313244;
             position:sticky; top:0; z-index:100; }}
  .topbar h1 {{ font-size:1rem; color:#cba6f7; margin:0; }}
  .nav a {{ color:#a6adc8; text-decoration:none; padding:4px 10px;
            border:1px solid #45475a; border-radius:5px; font-size:0.82rem; }}
  .nav a:hover {{ background:#313244; }}
  .content {{ padding:16px 20px; max-width:1400px; margin:0 auto; }}
  details {{ margin-bottom:8px; }}
  summary {{ cursor:pointer; padding:6px 10px; border-radius:5px; }}
  summary:hover {{ filter:brightness(1.15); }}
  .blk-hdr {{ font-weight:600; font-size:0.88rem; }}
  .blk-text {{ background:#1e3a5f; }}
  .blk-img  {{ background:#3a1e4f; }}
  .blk-body {{ padding:8px 16px; }}
  .ln-hdr {{ background:#252535; font-size:0.82rem; }}
  .gap {{ color:#f38ba8; font-size:0.8em; margin-left:8px; }}
  .span-tbl {{ width:100%; border-collapse:collapse; margin:6px 0;
               font-size:0.82rem; }}
  .span-tbl th {{ background:#313244; padding:4px 8px; text-align:left; }}
  .span-tbl td {{ padding:3px 8px; border-bottom:1px solid #2a2a3a; }}
  .cell-text {{ font-family:monospace; white-space:pre-wrap;
               max-width:280px; word-break:break-all; }}
  .cell-font {{ font-family:monospace; font-size:0.78em;
               max-width:200px; word-break:break-all; }}
  .swatch {{ display:inline-block; width:12px; height:12px;
            border:1px solid #585b70; vertical-align:middle;
            margin-right:4px; border-radius:2px; }}
  .pua {{ color:#f38ba8; font-size:0.75em; }}
  .img-note {{ color:#a6e3a1; }}
  .section-hdr {{ color:#89b4fa; font-size:0.9rem; font-weight:700;
                  margin:20px 0 8px; border-bottom:1px solid #313244;
                  padding-bottom:4px; }}
  .plain {{ background:#181825; padding:12px 16px; border-radius:6px;
            white-space:pre-wrap; font-family:monospace; font-size:0.82rem;
            max-height:300px; overflow-y:auto; color:#a6e3a1; }}
  table.img-tbl {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
  table.img-tbl th {{ background:#313244; padding:4px 8px; text-align:left; }}
  table.img-tbl td {{ padding:3px 8px; border-bottom:1px solid #2a2a3a; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>🔍 RAW EXTRACTION DEBUG</h1>
  <span>Page {page_index+1} / {total}
    &nbsp;|&nbsp; {pw_pt:.0f} × {ph_pt:.0f} pt
    &nbsp;|&nbsp; {len(blocks)} blocks
  </span>
  <div class="nav">
    {"" if page_index == 0 else
     f'<a href="?page={page_index-1}">← Prev</a>'}
    &nbsp;
    {"" if page_index >= total-1 else
     f'<a href="?page={page_index+1}">Next →</a>'}
  </div>
</div>

<div class="content">

  <div class="section-hdr">📄 PLAIN TEXT (get_text("text"))</div>
  <pre class="plain">{html.escape(plain_text)}</pre>

  <div class="section-hdr">🧱 BLOCK / LINE / SPAN DETAIL (get_text("dict"))</div>
  {blocks_json}

  <div class="section-hdr">🖼 IMAGES (page.get_images(full=True))</div>
  <table class="img-tbl">
    <thead><tr>
      <th>#</th><th>xref</th><th>size (px)</th>
      <th>colorspace</th><th>filter</th><th>display rects (pt)</th>
    </tr></thead>
    <tbody>{img_rows if img_rows else '<tr><td colspan="6">No images found</td></tr>'}</tbody>
  </table>

</div>
</body>
</html>"""
