import base64
import re
from collections import Counter

import fitz  # PyMuPDF

RENDER_WIDTH   = 780    # max content width in px
MULTI_IMG_ZOOM = 1.5
MIN_IMG_PT     = 4


# ── PUA character fix ─────────────────────────────────────────────────────────

def _fix_pua(text: str) -> str:
    """Map PyMuPDF PUA fallback chars (U+E012+ASCII) back to real ASCII."""
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            corrected = cp - 0xE012
            if 0x20 <= corrected <= 0x7E:
                out.append(chr(corrected))
        else:
            out.append(ch)
    return "".join(out)


# ── Font CSS ──────────────────────────────────────────────────────────────────

def _get_font_css(page: fitz.Page) -> str:
    try:
        html = page.get_text("html",
                             flags=fitz.TEXT_PRESERVE_WHITESPACE
                                   | fitz.TEXT_MEDIABOX_CLIP)
        m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


# ── Alignment ─────────────────────────────────────────────────────────────────

def _is_centered(x0, x1, pw):
    ml, mr = x0, pw - x1
    return (ml > pw * 0.03
            and abs((x0+x1)/2 - pw/2) < pw * 0.12
            and abs(ml - mr) < pw * 0.20)


def _is_right(x0, x1, pw):
    return (pw - x1) < pw * 0.06 and x0 > pw * 0.35


def _font_flags(name: str) -> tuple[bool, bool]:
    """Detect bold/italic from font name (per PDF-to-EPUB skill guidance)."""
    n = name.lower()
    bold = (
        "bold"      in n or ",b"    in n or "-bd"   in n
        or "demi"   in n or "heavy" in n or "black" in n
        or "semibold" in n or "extrabold" in n or "ultrabold" in n
        or "medium" in n   # some fonts use medium as their "bold" weight
        or n.endswith("-w6") or n.endswith("-w7")
        or n.endswith("-w8") or n.endswith("-w9")
    )
    italic = (
        "italic" in n or "oblique" in n or "slanted" in n
        or n.endswith("-it") or n.endswith("-ital")
        or ",i" in n or "-it," in n
    )
    return bold, italic


def _extract_hr_lines(page: "fitz.Page", pw_pt: float) -> list[dict]:
    """Return horizontal rule items from vector drawings on the page.

    A horizontal rule is a path whose bounding rect is:
    - Very thin  (height < 4 pt)
    - Wide enough to be a visible separator (width > 25 % of page width)
    """
    hr_items: list[dict] = []
    try:
        for path in page.get_drawings():
            r = path.get("rect")
            if r is None:
                continue
            if r.height < 4 and r.width > pw_pt * 0.25:
                hr_items.append({"type": "hr", "y": float(r.y0)})
    except Exception:
        pass
    return hr_items


def _span_html(text: str, font: str, size_pt: float,
               r: int, g: int, b: int,
               bold: bool, italic: bool,
               include_size: bool = True,
               strikethrough: bool = False) -> str:
    """Return a single semantic HTML span for one PDF text run.

    Per pdf-to-epub skill:
    - Bold  → <strong>
    - Italic → <em>
    - Bold+Italic → <strong><em>
    - Plain → bare text inside <span>
    No redundant wrapping; font/size/color in the outer <span> style.
    """
    safe = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    # Semantic wrappers first
    if bold and italic:
        inner = f"<strong><em>{safe}</em></strong>"
    elif bold:
        inner = f"<strong>{safe}</strong>"
    elif italic:
        inner = f"<em>{safe}</em>"
    else:
        inner = safe

    # Strikethrough wraps the decorated content
    if strikethrough:
        inner = f"<del>{inner}</del>"

    # Outer <span> carries font-family and colour (and size for body text)
    parts = [f"font-family:'{font}',serif", f"color:rgb({r},{g},{b})"]
    if include_size:
        parts.append(f"font-size:{size_pt:.1f}pt")
    style = ";".join(parts)
    return f'<span style="{style}">{inner}</span>'


# ── Image helpers ─────────────────────────────────────────────────────────────

def _render_full_page(page, scale):
    zoom = scale * (96.0/72.0) * MULTI_IMG_ZOOM
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                           alpha=False, colorspace=fitz.csRGB)
    return base64.b64encode(pix.tobytes("png")).decode()


def _render_region(page, rect):
    try:
        if rect.width < MIN_IMG_PT or rect.height < MIN_IMG_PT:
            return None
        zoom = min(200.0 / min(rect.width, rect.height), 4.0)
        zoom = max(zoom, 1.0)
        pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                               clip=rect, alpha=False, colorspace=fitz.csRGB)
        return base64.b64encode(pix.tobytes("png")).decode()
    except Exception:
        return None


def _overlaps_text(img_bbox, txt_blks, threshold=0.05):
    """True if img bbox overlaps any single text block by > threshold of img area."""
    ix0, iy0, ix1, iy1 = img_bbox
    img_area = (ix1-ix0)*(iy1-iy0)
    if img_area <= 0:
        return False
    for tb in txt_blks:
        tx0, ty0, tx1, ty1 = tb["bbox"]
        ox = max(0.0, min(ix1,tx1)-max(ix0,tx0))
        oy = max(0.0, min(iy1,ty1)-max(iy0,ty0))
        if ox*oy/img_area > threshold:
            return True
    return False


def _covers_text_area(img_bbox, txt_blks, coverage=0.30):
    """True if the image bbox contains more than `coverage` fraction of the
    total text area on the page.  Catches large background / template images
    whose individual overlap with each text block is small but whose total
    footprint swallows most of the text — these must be filtered or the same
    content appears as both a rendered image AND editable text.
    """
    ix0, iy0, ix1, iy1 = img_bbox
    total_text = sum(
        (b["bbox"][2]-b["bbox"][0]) * (b["bbox"][3]-b["bbox"][1])
        for b in txt_blks
    )
    if total_text <= 0:
        return False
    contained = 0.0
    for tb in txt_blks:
        tx0, ty0, tx1, ty1 = tb["bbox"]
        ox = max(0.0, min(ix1,tx1)-max(ix0,tx0))
        oy = max(0.0, min(iy1,ty1)-max(iy0,ty0))
        contained += ox * oy
    return contained / total_text > coverage


# ── Heading detection ─────────────────────────────────────────────────────────

def _body_font_size(txt_blks: list) -> float:
    """Return the dominant body-text font size, weighted by character count.

    Weighting by character count prevents short noise elements (page numbers,
    running headers) from skewing the result.  Only spans with ≥ 4 characters
    are considered so single-digit page numbers are ignored.
    """
    size_chars: dict[float, int] = {}
    for blk in txt_blks:
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                text = sp["text"].strip()
                if len(text) < 4:          # skip page numbers, short labels
                    continue
                sz = round(sp["size"] * 2) / 2   # bucket to nearest 0.5pt
                size_chars[sz] = size_chars.get(sz, 0) + len(text)
    return max(size_chars, key=size_chars.get) if size_chars else 12.0


def _heading_tag(para_max_sz: float, body_size: float,
                 n_lines: int) -> str | None:
    """Return h1/h2/h3 only when confident this is a real heading.

    Requirements (all must be true):
    • Single-line block  — multi-line blocks are body paragraphs, not headings
    • Font ratio ≥ 1.5  — conservative threshold to avoid false positives
                          when body_size is slightly underestimated
    """
    if n_lines != 1:          # multi-line = paragraph, not heading
        return None
    if body_size <= 0:
        return None
    ratio = para_max_sz / body_size
    if ratio >= 2.0:  return "h1"
    if ratio >= 1.5:  return "h2"
    return None


# ── Page content builder ──────────────────────────────────────────────────────

def _is_standalone_block(blk, pw_pt: float) -> bool:
    """True if this block must NOT be merged with adjacent blocks.

    Detects TOC entries dynamically — works for any PDF regardless of format:

    Pattern 1  (\x08 tab marker, page 7 of this book):
        Line text contains \\x08 — an explicit right-tab used for dot leaders.

    Pattern 2  (negative-gap 2-line structure, page 8 of this book):
        Block has ≥ 2 lines where line[1] OVERLAPS line[0] vertically
        (gap < 2 pt) AND line[1] is a short integer (page number) positioned
        in the right 40 % of the page.
        Example:
            LINE 0: "Chapter 20: Voices from the Past"   x=(53–216)
            LINE 1: "164"                                 x=(293–311)  ← overlap

    No hard-coded page numbers or heading strings — purely structural.
    """
    lines = blk.get("lines", [])
    if not lines:
        return False

    # Pattern 1 — explicit \x08 tab
    for ln in lines:
        for sp in ln.get("spans", []):
            if '\x08' in sp["text"]:
                return True

    # Pattern 2 — two overlapping lines, line[1] = right-margin page number
    if len(lines) >= 2:
        gap = lines[1]["bbox"][1] - lines[0]["bbox"][3]   # negative = overlap
        if gap < 2:                                        # overlapping/touching
            ln1_text = "".join(
                sp["text"] for sp in lines[1].get("spans", [])
            ).strip()
            ln1_x0   = lines[1]["bbox"][0]
            is_num   = ln1_text.isdigit() and 1 <= int(ln1_text) <= 9999
            on_right = ln1_x0 > pw_pt * 0.55              # right 45 % of page
            if is_num and on_right:
                return True

    return False


def _render_toc_entry(blk) -> str:
    """Render a TOC entry as:  chapter title ···· page-number (flex row)."""
    lines = blk.get("lines", [])
    left_html = right_html = ""

    def _spans_html(spans: list) -> str:
        out = ""
        for sp in spans:
            text = _fix_pua(sp["text"]).replace('\x08', '').strip()
            if not text:
                continue
            c           = sp["color"]
            bold, italic = _font_flags(sp["font"])
            out += _span_html(
                text, sp["font"], sp["size"],
                (c>>16)&0xFF, (c>>8)&0xFF, c&0xFF,
                bold, italic, include_size=True
            )
        return out

    if lines:
        left_html  = _spans_html(lines[0].get("spans", []))
    if len(lines) > 1:
        right_html = _spans_html(lines[1].get("spans", []))

    if not left_html and not right_html:
        return ""

    return (f'<p style="display:flex;justify-content:space-between;'
            f'align-items:baseline;margin:0 0 0.2em 0;">'
            f'{left_html}'
            f'<span style="flex:1;border-bottom:1px dotted #aaa;'
            f'margin:0 5px 3px;"></span>'
            f'{right_html}</p>')


def _build_page_parts(page, pw_pt, scale, img_blks, txt_blks, page_area):
    """Return list of semantic HTML strings for one page.

    Paragraph detection
    ───────────────────
    PyMuPDF block = one logical unit (paragraph, TOC entry, heading, list item).
    Lines within the SAME block are merged into one <p> when their gap is small
    (< 60 % of line height).  Lines in DIFFERENT blocks are ALWAYS separate
    paragraphs — this correctly keeps TOC entries, list items, etc. separate.

    Why blocks matter:  a TOC has one block per chapter entry, so entries stay
    separate.  A body paragraph has one block with many close lines, so they
    merge into one reflowing <p>.

    Semantic tags
    ─────────────
    Font size relative to body text → h1 / h2 / h3 / p.
    """
    font_css = _get_font_css(page)
    parts: list[str] = []
    if font_css:
        parts.append(f'<style>{font_css}</style>')

    body_sz = _body_font_size(txt_blks)

    # ── Page right margin (for short-line detection within blocks) ────────
    right_margin = max(
        (ln["bbox"][2] for blk in txt_blks for ln in blk.get("lines", [])),
        default=pw_pt * 0.85,
    )

    # ── Strikethrough lines from vector drawings ──────────────────────────
    # Strikethrough is drawn as a short horizontal line over the text span.
    # Separator rules are full-width; strikethrough lines are narrow.
    strike_lines: list = []
    try:
        for path in page.get_drawings():
            r = path.get("rect")
            if r and r.height < 4 and 0 < r.width < pw_pt * 0.75:
                strike_lines.append(r)
    except Exception:
        pass

    def _is_struck(span_bbox) -> bool:
        """True if a drawing line passes through this span at its midpoint."""
        sx0, sy0, sx1, sy1 = span_bbox
        mid_y = (sy0 + sy1) / 2
        for sr in strike_lines:
            h_overlap = sr.x0 <= sx1 - 2 and sr.x1 >= sx0 + 2
            v_overlap  = sr.y0 - 4 <= mid_y <= sr.y1 + 4
            if h_overlap and v_overlap:
                return True
        return False

    # ── Sort blocks top→bottom ────────────────────────────────────────────
    sorted_blks = sorted(txt_blks,
                         key=lambda b: (round(b["bbox"][1]/2)*2, b["bbox"][0]))

    # ── Deduplicate overlapping blocks ────────────────────────────────────
    # Some PDFs (layered ebooks) place identical text at the same y-position
    # multiple times.  Keep only the first block at each unique y-top.
    seen_y: set[int] = set()
    deduped: list[dict] = []
    for blk in sorted_blks:
        y_key = round(blk["bbox"][1])
        if y_key not in seen_y:
            seen_y.add(y_key)
            deduped.append(blk)
    sorted_blks = deduped

    # ── One PyMuPDF block = one paragraph (NO merging, NO splitting) ──────
    # PyMuPDF already determined which lines belong together (same block)
    # and which are separate (different blocks).  We trust that completely.
    # Lines within a block are joined with a space; different blocks get
    # their own <p>.  This is the most faithful representation of the PDF.
    items: list[dict] = []

    for blk in sorted_blks:
        bx0, by0, bx1, by1 = blk["bbox"]

        # Skip text already drawn inside an image block
        if any(
            ix0 <= bx0 and iy0 <= by0 and ix1 >= bx1 and iy1 >= by1
            for ix0, iy0, ix1, iy1 in (b["bbox"] for b in img_blks)
        ):
            continue

        # TOC entry (tab-leader / right-aligned page number) → toc item
        if _is_standalone_block(blk, pw_pt):
            items.append({"type": "toc", "y": by0, "blk": blk, "pw_pt": pw_pt})
            continue

        # Regular text block → one paragraph per block, BUT split at
        # first-line-indent boundaries within the block.
        #
        # Signal: a line is "short" (ends well before the right margin)
        # AND the next line is "indented" (starts further right than the
        # block's own left edge).  This is the universal typography cue
        # for a paragraph break in justified body text.
        raw = sorted(blk.get("lines", []), key=lambda l: l["bbox"][1])
        indent_min = max(right_margin * 0.025, 6)   # ~2.5 % of page width

        current_group: list[dict] = []
        for i, ln in enumerate(raw):
            ld = {"spans": ln.get("spans", []),
                  "bbox":  ln["bbox"],
                  "bx0": bx0, "bx1": bx1}
            current_group.append(ld)

            if i < len(raw) - 1:
                nxt      = raw[i + 1]
                is_short    = ln["bbox"][2]   < right_margin * 0.85
                is_indented = nxt["bbox"][0]  > bx0 + indent_min
                if is_short and is_indented:
                    items.append({"type": "para", "y": current_group[0]["bbox"][1],
                                  "lines": current_group})
                    current_group = []

        if current_group:
            items.append({"type": "para", "y": current_group[0]["bbox"][1],
                          "lines": current_group})

    # ── Horizontal rules from vector drawings ─────────────────────────────
    for hr in _extract_hr_lines(page, pw_pt):
        items.append(hr)

    # ── Images ────────────────────────────────────────────────────────────
    for blk in img_blks:
        bx0, by0, bx1, by1 = blk["bbox"]
        items.append({"type": "img", "y": by0,
                      "bbox": (bx0, by0, bx1, by1)})

    items.sort(key=lambda x: x["y"])

    # ── Render ────────────────────────────────────────────────────────────
    seen_img_prints: set[str] = set()   # b64 fingerprints — catches duplicates

    for item in items:

        # ── Image ─────────────────────────────────────────────────────────
        if item["type"] == "img":
            bx0, by0, bx1, by1 = item["bbox"]
            iw, ih = bx1-bx0, by1-by0
            if iw < 12 or ih < 12:                                      continue
            if iw > 0 and ih > 0 and max(iw/ih, ih/iw) > 4.0:          continue
            mn = min(iw, ih)
            if mn > 0 and ih * min(200.0/mn, 4.0) > 600:                continue
            # Filter 1 – direct overlap
            if _overlaps_text(item["bbox"], txt_blks, threshold=0.20):   continue
            # Filter 2 – large background covering text area
            if _covers_text_area(item["bbox"], txt_blks, coverage=0.30):  continue

            b64 = _render_region(page, fitz.Rect(bx0, by0, bx1, by1))
            if not b64:
                continue

            # Filter 3 – duplicate image on same page.
            # The PDF may place the same image twice in its content stream.
            # The first 80 base64 chars form a reliable fingerprint:
            # identical renders always produce identical b64 prefixes.
            fp = b64[:80]
            if fp in seen_img_prints:
                continue
            seen_img_prints.add(fp)

            parts.append(
                f'<figure class="pdf-img-block" contenteditable="false" '
                f'style="text-align:center;margin:1.2em 0;position:relative;'
                f'cursor:pointer;">'
                f'<img src="data:image/png;base64,{b64}" '
                f'style="max-width:100%;height:auto;display:block;margin:0 auto;" '
                f'alt="" draggable="false"/></figure>'
            )
            continue

        # ── Horizontal rule ───────────────────────────────────────────────
        if item["type"] == "hr":
            parts.append(
                '<hr contenteditable="false" '
                'style="border:none;border-top:1px solid #333;'
                'margin:0.6em 0;"/>'
            )
            continue

        # ── TOC entry ─────────────────────────────────────────────────────
        if item["type"] == "toc":
            html_row = _render_toc_entry(item["blk"])
            if html_row:
                parts.append(html_row)
            continue

        # ── Paragraph / Heading ───────────────────────────────────────────
        lines = item["lines"]

        # Representative font size = max span size in paragraph
        para_max_sz = max(
            (sp["size"] for ln in lines for sp in ln["spans"] if sp["text"].strip()),
            default=body_sz
        )

        # Alignment from full paragraph bounding box
        all_x0 = min(l["bbox"][0] for l in lines)
        all_x1 = max(l["bbox"][2] for l in lines)
        if _is_centered(all_x0, all_x1, pw_pt):
            align = "center"
        elif _is_right(all_x0, all_x1, pw_pt):
            align = "right"
        else:
            align = "left"

        # Decide tag — only single-line blocks with large ratio become headings
        htag = _heading_tag(para_max_sz, body_sz, len(lines))
        tag  = htag if htag else "p"

        # Build inner HTML — use semantic <strong>/<em> per pdf-to-epub skill
        # Collect all raw span data first, then merge adjacent identical styles
        raw_spans: list[dict] = []
        for ln in lines:
            for sp in ln["spans"]:
                text = _fix_pua(sp["text"])
                if not text:
                    continue
                c = sp["color"]
                bold, italic = _font_flags(sp["font"])
                raw_spans.append({
                    "text":   text,
                    "font":   sp["font"],
                    "size":   sp["size"],
                    "r": (c>>16)&0xFF, "g": (c>>8)&0xFF, "b": c&0xFF,
                    "bold":   bold,
                    "italic": italic,
                    "bbox":   sp["bbox"],   # needed for strikethrough detection
                })
            # Paragraph line separator (flow layout — joins with space)
            if raw_spans and not raw_spans[-1]["text"].endswith(" "):
                raw_spans.append(None)   # sentinel = space between lines

        # Merge adjacent spans with identical style (pdf-to-epub: no redundant spans)
        merged: list[dict] = []
        for sp in raw_spans:
            if sp is None:
                if merged:
                    merged[-1]["text"] += " "
                continue
            if (merged and
                    merged[-1]["font"]   == sp["font"] and
                    merged[-1]["size"]   == sp["size"] and
                    merged[-1]["r"]      == sp["r"]    and
                    merged[-1]["bold"]   == sp["bold"] and
                    merged[-1]["italic"] == sp["italic"]):
                merged[-1]["text"] += sp["text"]
            else:
                merged.append(dict(sp))

        inner = "".join(
            _span_html(s["text"], s["font"], s["size"],
                       s["r"], s["g"], s["b"],
                       s["bold"], s["italic"],
                       include_size=(htag is None),
                       strikethrough=_is_struck(s["bbox"]))
            for s in merged
            if s["text"].strip()
        )

        if inner.strip():
            parts.append(f'<{tag} style="text-align:{align};">{inner}</{tag}>')

    return parts


# ── Main converter ────────────────────────────────────────────────────────────

def pdf_to_html(pdf_bytes: bytes) -> str:
    """Convert PDF to reflowable semantic HTML (EPUB-ready).

    • One white card per PDF page (natural height — no fixed A4)
    • h1/h2/h3 detected from font-size ratio relative to body text
    • Paragraphs grouped by vertical gap (empty line = new paragraph)
    • Images inline as <figure class="pdf-img-block">
    • Font subsets embedded via a single <style> block at the top
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_html: list[str] = []
    all_font_rules: set[str] = set()

    for page_num, page in enumerate(doc):
        try:
            pw_pt = page.rect.width
            ph_pt = page.rect.height
            pw_px = pw_pt * 96.0/72.0
            scale = RENDER_WIDTH / pw_px

            # Harvest @font-face rules
            css = _get_font_css(page)
            if css:
                for rule in re.findall(r"@font-face\s*\{[^}]+\}", css, re.DOTALL):
                    all_font_rules.add(rule.strip())

            flags = (fitz.TEXT_PRESERVE_WHITESPACE
                     | fitz.TEXT_MEDIABOX_CLIP
                     | fitz.TEXT_PRESERVE_IMAGES)
            raw      = page.get_text("dict", flags=flags)["blocks"]
            img_blks = [b for b in raw if b.get("type") == 1]
            txt_blks = [b for b in raw if b.get("type") == 0]

            total_chars = sum(
                len(sp["text"].strip())
                for b in txt_blks
                for ln in b.get("lines", [])
                for sp in ln.get("spans", [])
            )
            page_area = pw_pt * ph_pt
            img_area  = sum((b["bbox"][2]-b["bbox"][0])*(b["bbox"][3]-b["bbox"][1])
                            for b in img_blks)
            img_cov   = img_area / page_area if page_area > 0 else 0

            # Cover / full-bleed art pages → single rendered image
            if total_chars < 120 and img_cov > 0.35:
                b64    = _render_full_page(page, scale)
                ph_px2 = ph_pt * 96.0/72.0 * scale
                page_html = (
                    f'<div class="pdf-page" style="padding:0;">'
                    f'<img src="data:image/png;base64,{b64}" '
                    f'style="width:100%;height:auto;display:block;" alt=""/></div>'
                )
            else:
                parts = _build_page_parts(
                    page, pw_pt, scale, img_blks, txt_blks, page_area)
                page_html = (
                    f'<div class="pdf-page" contenteditable="true">'
                    + "".join(parts)
                    + "</div>"
                )

        except Exception as exc:
            page_html = (
                f'<div class="pdf-page" style="color:#c00;font-family:sans-serif;">'
                f'Page {page_num+1} error: {exc}</div>'
            )

        pages_html.append(page_html)

    doc.close()

    font_block = ""
    if all_font_rules:
        font_block = "<style>\n" + "\n".join(all_font_rules) + "\n</style>\n"

    return font_block + "\n".join(pages_html)
