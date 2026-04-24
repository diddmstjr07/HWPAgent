'use strict';

// ── Global state ──
let sessionId = null;
let pageCount = 0;
let currentPage = 0;
let apiKey = localStorage.getItem('hwp_api_key') ?? '';

// ── DOM refs ──
const apiKeyInput = document.getElementById('apiKeyInput');
const fileInput   = document.getElementById('fileInput');
const fileBtn     = document.getElementById('fileBtn');
const dropZone    = document.getElementById('dropZone');
const statusText  = document.getElementById('statusText');
const errorBanner = document.getElementById('errorBanner');
const svgContainer= document.getElementById('svgContainer');
const svgPlaceholder = document.getElementById('svgPlaceholder');
const pageInfo    = document.getElementById('pageInfo');
const prevBtn     = document.getElementById('prevBtn');
const nextBtn     = document.getElementById('nextBtn');
const opForm      = document.getElementById('opForm');
const opKind      = document.getElementById('opKind');
const applyBtn    = document.getElementById('applyBtn');
const exportBtn   = document.getElementById('exportBtn');

// ── Init ──
apiKeyInput.value = apiKey;
apiKeyInput.addEventListener('input', () => {
  apiKey = apiKeyInput.value.trim();
  localStorage.setItem('hwp_api_key', apiKey);
});

fileBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  if (file) uploadFile(file);
  fileInput.value = '';
});

dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  const file = e.dataTransfer?.files?.[0];
  if (file) uploadFile(file);
});

prevBtn.addEventListener('click', () => changePage(-1));
nextBtn.addEventListener('click', () => changePage(1));
exportBtn.addEventListener('click', exportHwp);
opKind.addEventListener('change', updateFormFields);
opForm.addEventListener('submit', (e) => { e.preventDefault(); submitOp(); });

// ── API helpers ──
function headers(extra = {}) {
  const h = { ...extra };
  if (apiKey) h['X-Api-Key'] = apiKey;
  return h;
}

function showError(msg, duration = 6000) {
  errorBanner.textContent = msg;
  errorBanner.classList.remove('hidden');
  clearTimeout(showError._timer);
  showError._timer = setTimeout(() => errorBanner.classList.add('hidden'), duration);
}

function setStatus(msg) {
  statusText.textContent = msg;
}

// ── Core API functions ──
async function uploadFile(file) {
  setStatus(`업로드 중…`);
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/sessions', { method: 'POST', headers: headers(), body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(`업로드 실패 (${res.status}): ${err.error ?? res.statusText}`);
      setStatus('');
      return;
    }
    const data = await res.json();
    sessionId = data.sessionId;
    pageCount = data.pageCount;
    currentPage = 0;
    setStatus(`${file.name} · ${pageCount}페이지`);
    applyBtn.disabled = false;
    exportBtn.disabled = false;
    updatePageNav();
    await renderPage(0);
  } catch (e) {
    showError(`오류: ${e.message}`);
    setStatus('');
  }
}

async function renderPage(index) {
  if (!sessionId) return;
  try {
    const res = await fetch(`/sessions/${sessionId}/pages/${index}`, { headers: headers() });
    if (!res.ok) {
      showError(`렌더 실패 (${res.status}): ${res.statusText}`);
      return;
    }
    const svg = await res.text();
    // Replace placeholder with SVG
    svgPlaceholder.classList.add('hidden');
    svgContainer.innerHTML = svg;
    currentPage = index;
    updatePageNav();
  } catch (e) {
    showError(`렌더 오류: ${e.message}`);
  }
}

async function applyOp(payload) {
  if (!sessionId) { showError('먼저 HWP 파일을 업로드하세요'); return; }
  try {
    const res = await fetch(`/sessions/${sessionId}/ops`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(`Op 실패 (${res.status}): ${err.error ?? res.statusText}`);
      return;
    }
    const data = await res.json();
    const affected = data.affectedPages ?? [];
    // Re-render current page if affected (or if we can't tell)
    if (affected.length === 0 || affected.includes(currentPage)) {
      await renderPage(currentPage);
    }
  } catch (e) {
    showError(`Op 오류: ${e.message}`);
  }
}

async function exportHwp() {
  if (!sessionId) return;
  try {
    const res = await fetch(`/sessions/${sessionId}/export`, { headers: headers() });
    if (!res.ok) {
      showError(`내보내기 실패 (${res.status}): ${res.statusText}`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // Try to get filename from Content-Disposition
    const cd = res.headers.get('content-disposition') ?? '';
    const match = cd.match(/filename="([^"]+)"/);
    a.download = match ? match[1] : 'export.hwp';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    showError(`내보내기 오류: ${e.message}`);
  }
}

// ── UI helpers ──
function updatePageNav() {
  const valid = sessionId && pageCount > 0;
  pageInfo.textContent = valid ? `${currentPage + 1} / ${pageCount}` : '— / —';
  prevBtn.disabled = !valid || currentPage <= 0;
  nextBtn.disabled = !valid || currentPage >= pageCount - 1;
}

function changePage(delta) {
  const next = currentPage + delta;
  if (next >= 0 && next < pageCount) renderPage(next);
}

function updateFormFields() {
  const kind = opKind.value;
  const show = (...ids) => ids.forEach(id => document.getElementById(id).classList.remove('hidden'));
  const hide = (...ids) => ids.forEach(id => document.getElementById(id).classList.add('hidden'));

  // Reset all optional fields
  hide('lengthField', 'newTextField', 'queryField', 'replacementField', 'alignField');
  show('secField', 'paraField', 'offsetField', 'textField');

  if (kind === 'delete_text') {
    hide('textField');
    show('lengthField');
  } else if (kind === 'replace_text') {
    hide('textField');
    show('lengthField', 'newTextField');
  } else if (kind === 'set_para_format') {
    hide('offsetField', 'textField');
    show('alignField');
  } else if (kind === 'search_replace_all') {
    hide('secField', 'paraField', 'offsetField', 'textField');
    show('queryField', 'replacementField');
  }
}

function submitOp() {
  if (!sessionId) { showError('먼저 HWP 파일을 업로드하세요'); return; }
  const kind = opKind.value;
  const sec  = Number(document.getElementById('sec').value);
  const para = Number(document.getElementById('para').value);

  let payload;

  if (kind === 'insert_text') {
    payload = { kind, sec, para, offset: Number(document.getElementById('offset').value), text: document.getElementById('text').value };
  } else if (kind === 'delete_text') {
    payload = { kind, sec, para, offset: Number(document.getElementById('offset').value), length: Number(document.getElementById('length').value) };
  } else if (kind === 'replace_text') {
    payload = { kind, sec, para, offset: Number(document.getElementById('offset').value), length: Number(document.getElementById('length').value), newText: document.getElementById('newText').value };
  } else if (kind === 'set_para_format') {
    payload = { kind, sec, para, props: { align: document.getElementById('align').value } };
  } else if (kind === 'search_replace_all') {
    payload = { kind, query: document.getElementById('query').value, replacement: document.getElementById('replacement').value };
  } else {
    showError(`알 수 없는 op 종류: ${kind}`);
    return;
  }

  applyOp(payload);
}

// ── Initial field state ──
updateFormFields();
updatePageNav();
