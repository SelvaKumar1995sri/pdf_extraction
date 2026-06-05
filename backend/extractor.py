import base64
import re

import fitz  # PyMuPDF

RENDER_WIDTH   = 794   # A4 width  at 96 DPI  (210 mm)
A4_MIN_H       = 1123  # A4 height at 96 DPI  (297 mm)
MIN_IMG_PT     = 4
MULTI_IMG_ZOOM = 1.5


# ── PUA character fix ─────────────────────────────────────────────────────────

def _fix_pua(text: str) -> str:
    """Recover real characters from PyMuPDF's PUA fallback encoding.

    When a PDF font has no ToUnicode entry for a glyph, PyMuPDF maps the raw
    character code `c` to  U+E000 + c.

    GambadoSans (and similar display fonts) store character codes as
    ASCII + 18, so  PUA = U+E000 + ASCII + 18 = U+E012 + ASCII.
    To recover:  ASCII = PUA − 0xE012

    Evidence from the current PDF:
        ] (0x5D) − 18 = 0x4B = K   ✓
        □ (0x84) − 18 = 0x72 = r   ✓   (0x84 was > 0x7E, blocked before)
        { (0x7B) − 18 = 0x69 = i   ✓
        v (0x76) − 18 = 0x64 = d   ✓
        S (0x53) − 18 = 0x41 = A   ✓
    """
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            corrected = cp - 0xE012          # subtract 0xE000 + 18
            if 0x20 <= corrected <= 0x7E:
                out.append(chr(corrected))   # valid printable ASCII
            # else: drop the unrenderable glyph
        else:
            out.append(ch)
    return "".join(out)


# ── Font CSS extraction ───────────────────────────────────────────────────────

def _get_font_css(page: fitz.Page) -> str:
    """Return the raw content of the <style> block from PyMuPDF's HTML output.

    PyMuPDF embeds every font used on the page as a base64 @font-face rule.
    Those rules map PUA code points → real glyphs, so headings like
    'On Kirrin Island Again' render correctly as text in the browser.

    IMPORTANT: this CSS must be placed OUTSIDE any contenteditable element.
    Browsers silently ignore <style> tags that live inside editable regions.
    """
    try:
        html = page.get_text(
            "html",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )
        m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


# ── Alignment helpers ─────────────────────────────────────────────────────────

def _is_centered(x0, x1, pw):
    ml, mr = x0, pw - x1
    return (ml > pw * 0.03
            and abs((x0+x1)/2 - pw/2) < pw * 0.12
            and abs(ml - mr) < pw * 0.20)


def _is_right(x0, x1, pw):
    return (pw - x1) < pw * 0.06 and x0 > pw * 0.35


def _font_flags(name):
    n = name.lower()
    bold   = "bold" in n or ",b" in n or "-bd" in n or "demi" in n or "heavy" in n
    italic = "italic" in n or "oblique" in n or ",i" in n
    return bold, italic


# ── Image helpers ─────────────────────────────────────────────────────────────

def _render_full_page(page, scale):
    zoom = scale * (96.0/72.0) * MULTI_IMG_ZOOM
    pix  = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                           alpha=False, colorspace=fitz.csRGB)
    return base64.b64encode(pix.tobytes("png")).decode()


def _render_region(page, rect, zoom=None):
    try:
        if rect.width < MIN_IMG_PT or rect.height < MIN_IMG_PT:
            return None
        if zoom is None:
            zoom = min(200.0 / min(rect.width, rect.height), 4.0)
            zoom = max(zoom, 1.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                              clip=rect, alpha=False, colorspace=fitz.csRGB)
        return base64.b64encode(pix.tobytes("png")).decode()
    except Exception:
        return None


def _overlaps_text(img_bbox, txt_blks, threshold=0.05):
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


# ── Page content builder ──────────────────────────────────────────────────────

def _build_page_parts(page, pw_pt, scale, img_blks, txt_blks, page_area):
    """Build the HTML content (images + text) for one page.

    Text spans use  font-family:'<PDF font name>'  which exactly matches the
    @font-face family names collected separately and injected at the top of the
    full HTML output (outside all contenteditable divs).
    PUA characters are kept as-is — the @font-face rules handle their display.
    """
    parts: list[str] = []
    all_blks = sorted(img_blks + txt_blks,
                      key=lambda b: (round(b["bbox"][1]/5)*5, b["bbox"][0]))

    for blk in all_blks:
        btype = blk.get("type")
        bx0, by0, bx1, by1 = blk["bbox"]

        # ── Inline image ──────────────────────────────────────────────────────
        if btype == 1:
            img_w = bx1 - bx0
            img_h = by1 - by0
            if img_w < 12 or img_h < 12:
                continue
            if img_w > 0 and img_h > 0:
                if max(img_w/img_h, img_h/img_w) > 4.0:
                    continue
            _mn = min(img_w, img_h)
            if _mn > 0 and img_h * min(200.0/_mn, 4.0) > 600:
                continue
            if _overlaps_text(blk["bbox"], txt_blks):
                continue
            b64 = _render_region(page, fitz.Rect(bx0, by0, bx1, by1))
            if b64:
                parts.append(
                    f'<div style="text-align:center;margin:10px 0;" '
                    f'contenteditable="false">'
                    f'<img src="data:image/png;base64,{b64}" '
                    f'style="max-width:100%;height:auto;display:block;margin:0 auto;" '
                    f'alt=""/></div>'
                )
            continue

        if btype != 0:
            continue

        # ── Text block ────────────────────────────────────────────────────────
        blk_c = _is_centered(bx0, bx1, pw_pt)
        blk_r = (not blk_c) and _is_right(bx0, bx1, pw_pt)

        for line in blk.get("lines", []):
            lx0, _, lx1, _ = line["bbox"]
            if blk_c or _is_centered(lx0, lx1, pw_pt):
                align = "center"
            elif blk_r or _is_right(lx0, lx1, pw_pt):
                align = "right"
            else:
                align = "left"

            spans_html = ""
            for sp in line.get("spans", []):
                # Apply PUA fix: U+E000+ascii → correct ASCII character
                text = _fix_pua(sp["text"])
                if not text:
                    continue
                sz   = sp["size"]
                font = sp["font"]
                c    = sp["color"]
                r, g, b = (c>>16)&0xFF, (c>>8)&0xFF, c&0xFF
                bold, italic = _font_flags(font)
                style = (f"font-size:{sz:.1f}pt;"
                         f"font-family:'{font}',serif;"
                         f"color:rgb({r},{g},{b});")
                if bold:   style += "font-weight:bold;"
                if italic: style += "font-style:italic;"
                safe = (text.replace("&","&amp;")
                            .replace("<","&lt;")
                            .replace(">","&gt;"))
                spans_html += f'<span style="{style}">{safe}</span>'

            if spans_html.strip():
                parts.append(
                    f'<div style="text-align:{align};line-height:1.6;'
                    f'margin:1px 0;overflow-wrap:break-word;">'
                    f'{spans_html}</div>'
                )

    return parts


# ── Main converter ────────────────────────────────────────────────────────────

def pdf_to_html(pdf_bytes: bytes) -> str:
    """Convert PDF to editable HTML.

    Font strategy
    ─────────────
    1. Call get_text("html") once per page to harvest @font-face rules.
    2. Deduplicate the rules across all pages.
    3. Emit ONE <style> block at the very top of the output — OUTSIDE every
       contenteditable div — so browsers apply the embedded fonts.
    4. Each text span references its PDF font name; the @font-face rule
       provides the matching glyph data including PUA code point mappings.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_html: list[str] = []
    all_font_rules: set[str] = set()   # deduplicated @font-face rules

    for page_num, page in enumerate(doc):
        try:
            pw_pt = page.rect.width
            ph_pt = page.rect.height
            pw_px = pw_pt * 96.0/72.0
            scale = RENDER_WIDTH / pw_px

            # Harvest font CSS for this page
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
            img_area  = sum(
                (b["bbox"][2]-b["bbox"][0])*(b["bbox"][3]-b["bbox"][1])
                for b in img_blks
            )
            img_cov = img_area/page_area if page_area > 0 else 0

            # Cover / full-bleed art pages
            if total_chars < 120 and img_cov > 0.35:
                b64    = _render_full_page(page, scale)
                ph_px2 = max(ph_pt * 96.0/72.0 * scale, A4_MIN_H)
                page_html = (
                    f'<div style="width:{RENDER_WIDTH}px;min-height:{A4_MIN_H}px;'
                    f'margin:0 auto 32px;background:#fff;'
                    f'box-shadow:0 2px 16px rgba(0,0,0,0.18);">'
                    f'<img src="data:image/png;base64,{b64}" '
                    f'style="width:{RENDER_WIDTH}px;height:{ph_px2:.0f}px;'
                    f'display:block;" alt=""/></div>'
                )
            else:
                parts = _build_page_parts(
                    page, pw_pt, scale, img_blks, txt_blks, page_area
                )
                page_html = (
                    f'<div contenteditable="true" '
                    f'style="width:{RENDER_WIDTH}px;min-height:{A4_MIN_H}px;'
                    f'padding:60px 56px;background:#fff;'
                    f'margin:0 auto 32px;'
                    f'box-shadow:0 2px 16px rgba(0,0,0,0.18);'
                    f'box-sizing:border-box;outline:none;'
                    f'font-family:serif;overflow-wrap:break-word;'
                    f'word-break:break-word;">'
                    + "".join(parts)
                    + "</div>"
                )

        except Exception as exc:
            page_html = (
                f'<div style="width:{RENDER_WIDTH}px;height:80px;'
                f'margin:0 auto 32px;background:#fff8f8;'
                f'border:1px solid #f88;display:flex;align-items:center;'
                f'justify-content:center;font-family:sans-serif;color:#c00;'
                f'font-size:13px;">'
                f'Page {page_num+1} could not be rendered: {exc}</div>'
            )

        pages_html.append(page_html)

    doc.close()

    # Single <style> block at the top — OUTSIDE all contenteditable divs
    # so browsers actually process and apply the embedded @font-face rules.
    font_block = ""
    if all_font_rules:
        font_block = "<style>\n" + "\n".join(all_font_rules) + "\n</style>\n"

    return font_block + "\n".join(pages_html)
