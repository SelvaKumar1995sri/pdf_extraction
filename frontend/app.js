const API_BASE = "http://localhost:8000";

const pdfInput    = document.getElementById("pdfInput");
const uploadBtn   = document.getElementById("uploadBtn");
const debugBtn    = document.getElementById("debugBtn");
const dlWrap      = document.getElementById("dlWrap");
const dlToggle    = document.getElementById("dlToggle");
const dlMenu      = document.getElementById("dlMenu");
const statusMsg   = document.getElementById("statusMsg");

let extractedHtml = "";   // stored after each successful extraction
const pdfWrap     = document.getElementById("pdfViewerWrap");
const htmlPreview = document.getElementById("htmlPreview");
const divider     = document.getElementById("divider");
const syncTrack   = document.getElementById("syncTrack");
const syncThumb   = document.getElementById("syncThumb");
const panels      = document.querySelector(".panels");

let selectedFile  = null;
let objectUrl     = null;
let totalPages    = 1;      // updated after extraction
let currentPage   = 0;      // last page navigated to in the PDF iframe

// ── File selection ──────────────────────────────────────────────────────────
pdfInput.addEventListener("change", () => {
  const file = pdfInput.files[0];
  if (!file) return;
  selectedFile = file;
  uploadBtn.disabled = false;
  debugBtn.disabled  = false;
  setStatus(`Selected: ${file.name}`);
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  showPdfViewer(objectUrl);
  htmlPreview.innerHTML = '<div class="placeholder">Click Extract to process this PDF.</div>';
  currentPage = 0;
  refreshThumb();
});

// ── Extract button ──────────────────────────────────────────────────────────
uploadBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  uploadBtn.disabled = true;
  setStatus("Extracting…");
  htmlPreview.innerHTML = `
    <div class="spinner-wrap">
      <div class="spinner"></div>
      <span>Extracting content…</span>
    </div>`;
  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    const res = await fetch(`${API_BASE}/extract`, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Server error");
    }
    const data = await res.json();
    htmlPreview.innerHTML = data.html;
    extractedHtml = data.html;          // store for download
    totalPages = data.pages || 1;
    setStatus("Done.");
    dlWrap.style.display = "";          // show download button
    setTimeout(refreshThumb, 150);
    initImageInteraction();
  } catch (err) {
    htmlPreview.innerHTML = `<div class="placeholder" style="color:#c0392b">Error: ${escHtml(err.message)}</div>`;
    setStatus(`Error: ${err.message}`, true);
  } finally {
    uploadBtn.disabled = false;
  }
});

// ── Download dropdown ────────────────────────────────────────────────────────
dlToggle.addEventListener("click", e => {
  e.stopPropagation();
  dlMenu.classList.toggle("open");
});
document.addEventListener("click", () => dlMenu.classList.remove("open"));

dlMenu.querySelectorAll("button[data-fmt]").forEach(btn => {
  btn.addEventListener("click", async () => {
    dlMenu.classList.remove("open");
    const fmt = btn.dataset.fmt;
    if (!extractedHtml) { setStatus("Nothing extracted yet.", true); return; }

    const title  = selectedFile ? selectedFile.name.replace(/\.pdf$/i, "") : "Extracted Book";
    setStatus(`Preparing ${fmt.toUpperCase()}…`);

    try {
      const res = await fetch(`${API_BASE}/download/${fmt}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ html: extractedHtml, title }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Server error");
      }
      const blob     = await res.blob();
      const url      = URL.createObjectURL(blob);
      const anchor   = document.createElement("a");
      anchor.href     = url;
      anchor.download = `${title}.${fmt}`;
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus(`${fmt.toUpperCase()} downloaded.`);
    } catch (err) {
      setStatus(`Download failed: ${err.message}`, true);
    }
  });
});

// ── Debug button — opens raw extraction in a new tab ────────────────────────
debugBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  // Ask which page to debug (default = current PDF page shown, fallback 0)
  const pageInput = prompt(
    `Debug raw extraction.\nEnter page number (1-based):`,
    String(currentPage || 1)
  );
  if (pageInput === null) return;                 // cancelled
  const pageIdx = Math.max(0, parseInt(pageInput, 10) - 1) || 0;

  debugBtn.disabled = true;
  setStatus("Loading debug view…");
  try {
    const fd = new FormData();
    fd.append("file", selectedFile);
    const res  = await fetch(`${API_BASE}/debug?page=${pageIdx}`,
                             { method: "POST", body: fd });
    const html = await res.text();
    // Open result in a new tab
    const blob = new Blob([html], { type: "text/html" });
    const url  = URL.createObjectURL(blob);
    window.open(url, "_blank");
    setStatus("Debug view opened in new tab.");
  } catch (err) {
    setStatus(`Debug error: ${err.message}`, true);
  } finally {
    debugBtn.disabled = false;
  }
});

// ── PDF viewer (iframe for page navigation support) ─────────────────────────
function showPdfViewer(url) {
  pdfWrap.innerHTML =
    `<iframe id="pdfFrame" src="${url}" style="width:100%;height:100%;border:none;" allowfullscreen></iframe>`;
}

function navigatePdfToPage(page) {
  const p = Math.max(1, Math.min(totalPages, page));
  if (p === currentPage) return;          // nothing changed
  currentPage = p;
  const frame = document.getElementById("pdfFrame");
  if (!frame || !objectUrl) return;
  // Update src with page fragment — Chrome/Edge PDF viewer honours #page=N
  frame.src = objectUrl + "#page=" + p;
}

// ── Status helpers ──────────────────────────────────────────────────────────
function setStatus(msg, isError = false) {
  statusMsg.textContent = msg;
  statusMsg.className = "status" + (isError ? " error" : "");
}
function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Resizable divider ───────────────────────────────────────────────────────
let divDrag = false, divStartX = 0, divLeftW = 0;

divider.addEventListener("mousedown", e => {
  divDrag    = true;
  divStartX  = e.clientX;
  divLeftW   = panels.querySelector(".pdf-panel").offsetWidth;
  divider.classList.add("dragging");
  document.body.style.userSelect = "none";
});

document.addEventListener("mousemove", e => {
  if (!divDrag) return;
  const centerW = document.getElementById("centerBar").offsetWidth;
  const totalW  = panels.offsetWidth - centerW;
  const newL    = Math.min(Math.max(divLeftW + e.clientX - divStartX, totalW * 0.2), totalW * 0.8);
  panels.querySelector(".pdf-panel").style.flex    = `0 0 ${newL}px`;
  panels.querySelector(".preview-panel").style.flex = `0 0 ${totalW - newL}px`;
});

document.addEventListener("mouseup", () => {
  if (!divDrag) return;
  divDrag = false;
  divider.classList.remove("dragging");
  document.body.style.userSelect = "";
});

// ── Sync scroll helpers ─────────────────────────────────────────────────────
let syncLock = false;

function maxScroll(el) {
  return Math.max(0, el.scrollHeight - el.clientHeight);
}

function currentRatio() {
  const m = maxScroll(htmlPreview);
  return m > 0 ? htmlPreview.scrollTop / m : 0;
}

/** Apply a 0–1 ratio to both panels */
function applyRatio(ratio) {
  const r = Math.max(0, Math.min(1, ratio));
  syncLock = true;

  // Right panel: scroll the HTML content
  htmlPreview.scrollTop = r * maxScroll(htmlPreview);

  // Left panel: navigate PDF iframe to the corresponding page
  const targetPage = Math.max(1, Math.round(r * totalPages));
  navigatePdfToPage(targetPage);

  syncLock = false;
  positionThumb(r);
}

// ── Sync scrollbar thumb ────────────────────────────────────────────────────
function calcThumbH() {
  const trackH = syncTrack.clientHeight;
  const viewH  = htmlPreview.clientHeight;
  const total  = viewH + maxScroll(htmlPreview);
  return Math.max(32, Math.round(trackH * (total > 0 ? viewH / total : 1)));
}

function positionThumb(ratio) {
  const trackH = syncTrack.clientHeight;
  const thumbH = calcThumbH();
  syncThumb.style.height = thumbH + "px";
  syncThumb.style.top    = (ratio * (trackH - thumbH)) + "px";
}

function refreshThumb() {
  positionThumb(currentRatio());
}

// ── Right panel scroll → keep thumb in sync ─────────────────────────────────
htmlPreview.addEventListener("scroll", () => {
  if (syncLock) return;
  const r = currentRatio();
  // Also navigate PDF to corresponding page
  navigatePdfToPage(Math.max(1, Math.round(r * totalPages)));
  positionThumb(r);
});

// ── Mouse-wheel over EITHER panel → scroll both ─────────────────────────────
function onWheel(e) {
  e.preventDefault();
  htmlPreview.scrollTop += e.deltaY;
  const r = currentRatio();
  navigatePdfToPage(Math.max(1, Math.round(r * totalPages)));
  positionThumb(r);
}
htmlPreview.addEventListener("wheel", onWheel, { passive: false });
pdfWrap.addEventListener("wheel",     onWheel, { passive: false });

// ── Thumb drag ──────────────────────────────────────────────────────────────
let thumbDrag = false, thumbStartY = 0, thumbStartTop = 0;

syncThumb.addEventListener("mousedown", e => {
  thumbDrag     = true;
  thumbStartY   = e.clientY;
  thumbStartTop = parseFloat(syncThumb.style.top) || 0;
  syncThumb.classList.add("grabbing");
  document.body.style.userSelect = "none";
  e.stopPropagation();
  e.preventDefault();
});

document.addEventListener("mousemove", e => {
  if (!thumbDrag) return;
  const trackH = syncTrack.clientHeight;
  const thumbH = syncThumb.clientHeight;
  const maxTop = Math.max(0, trackH - thumbH);
  const newTop = Math.max(0, Math.min(maxTop, thumbStartTop + e.clientY - thumbStartY));
  const ratio  = maxTop > 0 ? newTop / maxTop : 0;
  applyRatio(ratio);
});

document.addEventListener("mouseup", () => {
  if (!thumbDrag) return;
  thumbDrag = false;
  syncThumb.classList.remove("grabbing");
  document.body.style.userSelect = "";
});

// ── Click on track ──────────────────────────────────────────────────────────
syncTrack.addEventListener("click", e => {
  if (e.target === syncThumb) return;
  const rect   = syncTrack.getBoundingClientRect();
  const thumbH = calcThumbH();
  const clickY = e.clientY - rect.top - thumbH / 2;
  const ratio  = Math.max(0, Math.min(1, clickY / Math.max(1, syncTrack.clientHeight - thumbH)));
  applyRatio(ratio);
});

// ── Refresh thumb on window resize ─────────────────────────────────────────
window.addEventListener("resize", refreshThumb);

// ── Image interaction ─────────────────────────────────────────────────────────
// Click        → select (purple ring + Delete toolbar)
// Drag         → pointer-event drag (works inside contenteditable)
// Delete key   → remove selected image
// Ctrl + Z     → restore last deleted image

// Unified undo stack — records both moves and deletes
// Each entry: { type: 'move'|'delete', div, parent, nextSibling }
const actionStack = [];
let   ptrDiv      = null;        // image being dragged
let   ptrGhost    = null;        // ghost clone following cursor
let   ptrOffX     = 0;
let   ptrOffY     = 0;
let   dropLine    = null;        // purple line showing insertion point
let   dropInfo    = null;        // {parent, beforeEl} — resolved on mouseup

function initImageInteraction() { /* handlers are delegated — nothing per-block needed */ }

// ── Delegated mousedown ───────────────────────────────────────────────────────
htmlPreview.addEventListener("mousedown", e => {
  if (e.target.closest(".img-toolbar")) return;   // let toolbar buttons fire

  const block = e.target.closest(".pdf-img-block");
  if (!block) { clearImageSelection(); return; }

  e.preventDefault();   // stops contenteditable node-selection

  if (block.classList.contains("img-selected")) {
    // Second click on already-selected → start drag
    _startPointerDrag(block, e);
  } else {
    clearImageSelection();
    _selectImage(block);
  }
});

// ── Select ────────────────────────────────────────────────────────────────────
function _selectImage(div) {
  clearImageSelection();
  div.classList.add("img-selected");

  const bar = document.createElement("div");
  bar.className = "img-toolbar";
  bar.innerHTML = `<button class="btn-delete">🗑 Delete</button>`;

  bar.querySelector(".btn-delete").addEventListener("mousedown", ev => {
    ev.stopPropagation();
    _deleteImage(div);
  });
  div.appendChild(bar);
}

function clearImageSelection() {
  htmlPreview.querySelectorAll(".pdf-img-block.img-selected").forEach(d => {
    d.classList.remove("img-selected");
    d.querySelector(".img-toolbar")?.remove();
  });
}

// ── Delete — push to undo stack ───────────────────────────────────────────────
function _deleteImage(div) {
  actionStack.push({ type: 'delete', div, parent: div.parentNode, nextSibling: div.nextSibling });
  div.remove();
}

// ── Pointer-event drag ────────────────────────────────────────────────────────
function _startPointerDrag(div, e) {
  ptrDiv  = div;
  const r = div.getBoundingClientRect();
  ptrOffX = e.clientX - r.left;
  ptrOffY = e.clientY - r.top;

  // Ghost: scaled-down copy of the image
  ptrGhost = document.createElement("div");
  ptrGhost.className = "img-ghost";
  const img = div.querySelector("img");
  if (img) {
    const gi = img.cloneNode(true);
    gi.style.cssText = "max-width:180px;height:auto;display:block;";
    ptrGhost.appendChild(gi);
  }
  document.body.appendChild(ptrGhost);

  // Drop indicator line
  dropLine = document.createElement("div");
  dropLine.className = "img-drop-line";
  htmlPreview.appendChild(dropLine);

  div.style.opacity = "0.2";
  div.querySelector(".img-toolbar")?.remove();
  div.classList.remove("img-selected");

  document.addEventListener("mousemove", _onPtrMove);
  document.addEventListener("mouseup",   _onPtrUp,   { once: true });
}

function _onPtrMove(e) {
  // Move ghost
  ptrGhost.style.left = (e.clientX - ptrOffX) + "px";
  ptrGhost.style.top  = (e.clientY - ptrOffY) + "px";

  // Resolve insertion point
  dropInfo = _resolveInsert(e.clientX, e.clientY);

  if (dropInfo) {
    const pr   = htmlPreview.getBoundingClientRect();
    const refEl = dropInfo.beforeEl || dropInfo.parent.lastElementChild;
    const lineY = dropInfo.beforeEl
      ? dropInfo.beforeEl.getBoundingClientRect().top  - pr.top + htmlPreview.scrollTop - 2
      : (refEl ? refEl.getBoundingClientRect().bottom - pr.top + htmlPreview.scrollTop + 2 : 0);

    dropLine.style.display = "block";
    dropLine.style.top     = lineY + "px";
  } else {
    dropLine.style.display = "none";
  }
}

function _onPtrUp(e) {
  document.removeEventListener("mousemove", _onPtrMove);

  ptrGhost?.remove();  ptrGhost = null;
  dropLine?.remove();  dropLine = null;

  if (ptrDiv) {
    ptrDiv.style.opacity = "";

    if (dropInfo) {
      // Record the CURRENT position before moving (for undo)
      const prevParent = ptrDiv.parentNode;
      const prevNext   = ptrDiv.nextSibling;
      const moved      = dropInfo.parent !== prevParent || dropInfo.beforeEl !== ptrDiv.nextSibling;

      if (moved) {
        dropInfo.parent.insertBefore(ptrDiv, dropInfo.beforeEl);
        actionStack.push({
          type:        'move',
          div:         ptrDiv,
          parent:      prevParent,
          nextSibling: prevNext
        });
      }
    }

    _selectImage(ptrDiv);
    ptrDiv = null;
  }
  dropInfo = null;
}

// Find which {parent, beforeEl} best matches cursor (x, y)
function _resolveInsert(cx, cy) {
  let best = null, bestDist = Infinity;

  htmlPreview.querySelectorAll("[contenteditable='true']").forEach(page => {
    const kids = [...page.children];
    // Check gap before each child + after last
    for (let i = 0; i <= kids.length; i++) {
      if (kids[i] === ptrDiv) continue;

      let lineY;
      if (i === 0) {
        lineY = page.getBoundingClientRect().top;
      } else {
        const prev = kids[i - 1];
        if (prev === ptrDiv) continue;
        lineY = prev.getBoundingClientRect().bottom;
      }

      const dist = Math.abs(cy - lineY);
      if (dist < bestDist) {
        bestDist = dist;
        best = { parent: page, beforeEl: kids[i] ?? null };
      }
    }
  });
  return best;
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", e => {
  // Ctrl + Z → undo last move or delete
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    const last = actionStack.pop();
    if (last) {
      e.preventDefault();
      const { div, parent, nextSibling } = last;
      // Restore to recorded position
      if (nextSibling && parent.contains(nextSibling)) {
        parent.insertBefore(div, nextSibling);
      } else {
        parent.appendChild(div);
      }
      _selectImage(div);
      div.scrollIntoView({ block: "nearest" });
    }
    return;
  }

  // Delete / Backspace key → remove selected image
  const sel = htmlPreview.querySelector(".pdf-img-block.img-selected");
  if (sel && (e.key === "Delete" || e.key === "Backspace")) {
    // Only if focus is not inside a text span
    const active = document.activeElement;
    if (!active || active === document.body || active === htmlPreview) {
      _deleteImage(sel);
    }
  }
});
