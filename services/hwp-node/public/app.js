'use strict';

// ── State ──
let sessionId  = null;
let pageCount  = 0;
let currentPage = 0;
let apiKey     = localStorage.getItem('hwp_api_key') ?? '';
let activeOp   = 'insert_text';
let toastTimer = null;

// ── DOM ──
const $  = (id) => document.getElementById(id);
const apiKeyInput   = $('apiKeyInput');
const fileInput     = $('fileInput');
const topUploadBtn  = $('topUploadBtn');
const topExportBtn  = $('topExportBtn');
const dropZone      = $('dropZone');
const dzOpenBtn     = $('dzOpenBtn');
const emptyState    = $('emptyState');
const viewerWrapper = $('viewerWrapper');
const sidebar       = $('sidebar');
const svgScroll     = $('svgScroll');
const svgSkeleton   = $('svgSkeleton');
const pageInfo      = $('pageInfo');
const prevBtn       = $('prevBtn');
const nextBtn       = $('nextBtn');
const opForm        = $('opForm');
const applyBtn      = $('applyBtn');
const fileBadge     = $('fileBadge');
const fileBadgeName = $('fileBadgeName');
const sidePageCount = $('sidePageCount');
const sideFileName  = $('sideFileName');
const toast         = $('toast');

// ── Init ──
apiKeyInput.value = apiKey;
apiKeyInput.addEventListener('input', () => {
  apiKey = apiKeyInput.value.trim();
  localStorage.setItem('hwp_api_key', apiKey);
});

topUploadBtn.addEventListener('click',   () => fileInput.click());
dzOpenBtn.addEventListener('click',      () => fileInput.click());
fileInput.addEventListener('change', (e) => {
  const f = e.target.files?.[0];
  if (f) uploadFile(f);
  fileInput.value = '';
});

// Drag & drop on whole empty state
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  const f = e.dataTransfer?.files?.[0];
  if (f) uploadFile(f);
});

// Page nav
prevBtn.addEventListener('click', () => changePage(-1));
nextBtn.addEventListener('click', () => changePage(1));

// Export
topExportBtn.addEventListener('click', exportHwp);

// Op tabs
document.querySelectorAll('.op-tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.op-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    activeOp = btn.dataset.op;
    updateFormFields();
  });
});

// Form submit
opForm.addEventListener('submit', (e) => { e.preventDefault(); submitOp(); });

// ── Toast ──
function showToast(msg, isError = false, duration = 4500) {
  toast.textContent = msg;
  toast.classList.toggle('error', isError);
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), duration);
}

// ── API helpers ──
function authHeaders(extra = {}) {
  return apiKey ? { 'X-Api-Key': apiKey, ...extra } : { ...extra };
}

// ── Core ──
async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  showLoading();
  try {
    const res = await fetch('/sessions', { method: 'POST', headers: authHeaders(), body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(`업로드 실패 (${res.status}): ${err.error ?? res.statusText}`, true);
      hideLoading();
      return;
    }
    const data = await res.json();
    sessionId  = data.sessionId;
    pageCount  = data.pageCount;
    currentPage = 0;

    // Update UI
    fileBadgeName.textContent = file.name;
    fileBadge.classList.add('loaded');
    sideFileName.textContent  = file.name;
    sidePageCount.textContent = String(pageCount);
    topExportBtn.disabled = false;
    applyBtn.disabled = false;

    // Show viewer
    emptyState.classList.add('hidden');
    viewerWrapper.classList.remove('hidden');
    sidebar.classList.remove('hidden');

    updatePageNav();
    await renderPage(0);
    showToast(`📄 ${file.name} 열림 — ${pageCount}페이지`);
  } catch (e) {
    showToast(`오류: ${e.message}`, true);
    hideLoading();
  }
}

async function renderPage(index) {
  if (!sessionId) return;
  showLoading();
  try {
    const res = await fetch(`/sessions/${sessionId}/pages/${index}`, { headers: authHeaders() });
    if (!res.ok) {
      showToast(`렌더 실패 (${res.status})`, true);
      hideLoading();
      return;
    }
    const svg = await res.text();
    // Clear existing SVG and inject new one
    svgScroll.querySelectorAll('svg').forEach(el => el.remove());
    svgScroll.insertAdjacentHTML('beforeend', svg);
    currentPage = index;
    updatePageNav();
  } catch (e) {
    showToast(`렌더 오류: ${e.message}`, true);
  } finally {
    hideLoading();
  }
}

async function applyOp(payload) {
  if (!sessionId) { showToast('먼저 HWP 파일을 업로드하세요', true); return; }
  applyBtn.classList.add('loading');
  applyBtn.disabled = true;
  try {
    const res = await fetch(`/sessions/${sessionId}/ops`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(`Op 실패: ${err.error ?? res.statusText}`, true);
      return;
    }
    const data = await res.json();
    const affected = data.affectedPages ?? [];
    if (affected.length === 0 || affected.includes(currentPage)) {
      await renderPage(currentPage);
    }
    showToast('✓ 적용됨');
  } catch (e) {
    showToast(`Op 오류: ${e.message}`, true);
  } finally {
    applyBtn.classList.remove('loading');
    applyBtn.disabled = false;
  }
}

async function exportHwp() {
  if (!sessionId) return;
  try {
    const res = await fetch(`/sessions/${sessionId}/export`, { headers: authHeaders() });
    if (!res.ok) { showToast(`내보내기 실패 (${res.status})`, true); return; }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    const cd = res.headers.get('content-disposition') ?? '';
    const m  = cd.match(/filename="([^"]+)"/);
    a.download = m ? m[1] : 'export.hwp';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('⬇ 다운로드 시작');
  } catch (e) {
    showToast(`내보내기 오류: ${e.message}`, true);
  }
}

// ── UI helpers ──
function showLoading() { svgSkeleton.classList.remove('hidden'); }
function hideLoading()  { svgSkeleton.classList.add('hidden'); }

function updatePageNav() {
  const ok = sessionId && pageCount > 0;
  pageInfo.textContent = ok ? `${currentPage + 1} / ${pageCount}` : '— / —';
  prevBtn.disabled = !ok || currentPage <= 0;
  nextBtn.disabled = !ok || currentPage >= pageCount - 1;
}

function changePage(delta) {
  const n = currentPage + delta;
  if (n >= 0 && n < pageCount) renderPage(n);
}

function updateFormFields() {
  const show = (...ids) => ids.forEach(id => $(id)?.classList.remove('hidden'));
  const hide = (...ids) => ids.forEach(id => $(id)?.classList.add('hidden'));

  // Default: show sec/para row + offset + textField
  show('secParaRow', 'offsetField', 'textField');
  hide('lengthField', 'newTextField', 'queryField', 'replacementField', 'alignField');

  if (activeOp === 'delete_text') {
    hide('textField');
    show('lengthField');
  } else if (activeOp === 'replace_text') {
    hide('textField');
    show('lengthField', 'newTextField');
  } else if (activeOp === 'set_para_format') {
    hide('offsetField', 'textField');
    show('alignField');
  } else if (activeOp === 'search_replace_all') {
    hide('secParaRow', 'offsetField', 'textField');
    show('queryField', 'replacementField');
  }
}

function submitOp() {
  if (!sessionId) { showToast('먼저 HWP 파일을 업로드하세요', true); return; }
  const sec  = Number($('sec')?.value ?? 0);
  const para = Number($('para')?.value ?? 0);
  let payload;

  if (activeOp === 'insert_text') {
    payload = { kind: activeOp, sec, para, offset: Number($('offset').value), text: $('text').value };
  } else if (activeOp === 'delete_text') {
    payload = { kind: activeOp, sec, para, offset: Number($('offset').value), length: Number($('length').value) };
  } else if (activeOp === 'replace_text') {
    payload = { kind: activeOp, sec, para, offset: Number($('offset').value), length: Number($('length').value), newText: $('newText').value };
  } else if (activeOp === 'set_para_format') {
    payload = { kind: activeOp, sec, para, props: { align: $('align').value } };
  } else if (activeOp === 'search_replace_all') {
    payload = { kind: activeOp, query: $('query').value, replacement: $('replacement').value };
  } else {
    return;
  }

  applyOp(payload);
}

// ── Boot ──
updateFormFields();
updatePageNav();
