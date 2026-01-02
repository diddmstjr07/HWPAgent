const statusEl = document.getElementById('status');
const targetEl = document.getElementById('targetBase');
const form = document.getElementById('loginForm');
const quitBtn = document.getElementById('quitBtn');

const setStatus = (message, isError = false) => {
  statusEl.textContent = message;
  statusEl.classList.toggle('error', isError);
};

const hydrateTarget = async () => {
  if (!window.adminBridge) {
    return;
  }
  const config = await window.adminBridge.getConfig();
  if (config && config.targetBase) {
    targetEl.textContent = config.targetBase;
  }
};

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = document.getElementById('adminId').value.trim();
  const password = document.getElementById('adminPassword').value;

  if (!id || !password) {
    setStatus('Credentials are required.', true);
    setTimeout(() => window.adminBridge.quit(), 800);
    return;
  }

  setStatus('Verifying admin access...');
  const result = await window.adminBridge.login({ id, password });
  if (!result || !result.ok) {
    setStatus(result && result.error ? result.error : 'Access denied.', true);
    setTimeout(() => window.adminBridge.quit(), 800);
    return;
  }
  setStatus('Opening admin console...');
});

quitBtn.addEventListener('click', () => {
  window.adminBridge.quit();
});

hydrateTarget();
