const API_BASE = "http://localhost:8000";

const pdfInput    = document.getElementById("pdfInput");
const uploadBtn   = document.getElementById("uploadBtn");
const statusMsg   = document.getElementById("statusMsg");
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
    totalPages = data.pages || 1;
    setStatus("Done.");
    setTimeout(refreshThumb, 150);
  } catch (err) {
    htmlPreview.innerHTML = `<div class="placeholder" style="color:#c0392b">Error: ${escHtml(err.message)}</div>`;
    setStatus(`Error: ${err.message}`, true);
  } finally {
    uploadBtn.disabled = false;
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
