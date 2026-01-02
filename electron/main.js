const { app, BrowserWindow, ipcMain, net, session, shell } = require('electron');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const dotenv = require('dotenv');

const APP_ICON_PATH = path.join(__dirname, 'assets', 'app-icon.png');
const DEFAULT_ADMIN_APP_TOKEN = 'G9zPjvkdeQQa3kLaJwlhHNamz0UgkN4lMBj-TWXrCxI';

const ADMIN_SIGN_PATHS = ['/admin', '/api/admin'];
let mainWindow = null;
let adminContext = null;
let cachedConfig = null;

const resolveEnvPath = () => {
  const userEnv = path.join(app.getPath('userData'), '.env');
  if (fs.existsSync(userEnv)) {
    return userEnv;
  }
  const prodEnv = path.join(process.resourcesPath || '', '.env');
  if (fs.existsSync(prodEnv)) {
    return prodEnv;
  }
  const devEnv = path.join(__dirname, '..', '.env');
  if (fs.existsSync(devEnv)) {
    return devEnv;
  }
  return null;
};

const loadEnv = () => {
  const envPath = resolveEnvPath();
  if (!envPath) {
    return;
  }
  dotenv.config({ path: envPath });
};

const getConfig = () => {
  if (cachedConfig) {
    return cachedConfig;
  }
  const targetBase = 'https://agent.diddmstjr.com';
  const targetOrigin = new URL(targetBase).origin;
  cachedConfig = {
    targetBase,
    targetOrigin,
    adminToken: process.env.ADMIN_ACCESS_TOKEN || '',
    adminSecret: process.env.ADMIN_SIGNATURE_SECRET || '',
    appToken: process.env.ADMIN_APP_TOKEN || DEFAULT_ADMIN_APP_TOKEN
  };
  return cachedConfig;
};

const signPayload = (method, pathValue, timestamp, token, secret) => {
  const payload = `${method}:${pathValue}:${timestamp}:${token}`;
  return crypto.createHmac('sha256', secret).update(payload).digest('hex');
};

const parseSetCookie = (cookieValue) => {
  if (!cookieValue) {
    return null;
  }
  const parts = cookieValue.split(';').map((part) => part.trim()).filter(Boolean);
  if (parts.length === 0) {
    return null;
  }
  const [nameValue, ...attrs] = parts;
  const separatorIdx = nameValue.indexOf('=');
  if (separatorIdx <= 0) {
    return null;
  }
  const cookie = {
    name: nameValue.slice(0, separatorIdx),
    value: nameValue.slice(separatorIdx + 1)
  };
  attrs.forEach((attr) => {
    const [rawKey, rawValue] = attr.split('=');
    const key = rawKey.toLowerCase();
    const value = rawValue ? rawValue.trim() : '';
    if (key === 'path') {
      cookie.path = value || '/';
    } else if (key === 'domain') {
      cookie.domain = value;
    } else if (key === 'expires') {
      const expires = Date.parse(value);
      if (!Number.isNaN(expires)) {
        cookie.expirationDate = Math.floor(expires / 1000);
      }
    } else if (key === 'max-age') {
      const maxAge = Number(value);
      if (!Number.isNaN(maxAge)) {
        cookie.expirationDate = Math.floor(Date.now() / 1000) + maxAge;
      }
    } else if (key === 'secure') {
      cookie.secure = true;
    } else if (key === 'httponly') {
      cookie.httpOnly = true;
    } else if (key === 'samesite') {
      const sameSite = value.toLowerCase();
      if (sameSite === 'lax') {
        cookie.sameSite = 'lax';
      } else if (sameSite === 'strict') {
        cookie.sameSite = 'strict';
      } else if (sameSite === 'none') {
        cookie.sameSite = 'no_restriction';
      }
    }
  });
  return cookie;
};

const applySetCookieHeaders = async (sessionObj, url, headers) => {
  if (!sessionObj || !headers) {
    return;
  }
  const setCookie = headers['set-cookie'];
  if (!setCookie) {
    return;
  }
  const cookieHeaders = Array.isArray(setCookie) ? setCookie : [setCookie];
  const cookieUrl = url.toString();
  await Promise.all(
    cookieHeaders.map(async (cookieHeader) => {
      const parsed = parseSetCookie(cookieHeader);
      if (!parsed || !parsed.name) {
        return;
      }
      try {
        await sessionObj.cookies.set({
          url: cookieUrl,
          ...parsed
        });
      } catch (err) {
        console.log(`[ADMIN] Failed to set cookie ${parsed.name}: ${err.message}`);
      }
    })
  );
};

const shouldSignPath = (pathname) => {
  return ADMIN_SIGN_PATHS.some((base) => pathname === base || pathname.startsWith(`${base}/`));
};

const buildCookieHeader = async (sessionObj, url) => {
  if (!sessionObj || !sessionObj.cookies) {
    return '';
  }
  try {
    const cookies = await sessionObj.cookies.get({ url });
    if (!cookies || cookies.length === 0) {
      return '';
    }
    return cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join('; ');
  } catch (err) {
    return '';
  }
};

const requestJson = async (sessionObj, url, method, body, extraHeaders = {}, appToken = '') => {
  const cookieHeader = await buildCookieHeader(sessionObj, url);
  return new Promise((resolve, reject) => {
    const request = net.request({ url, method, session: sessionObj });
    request.setHeader('Content-Type', 'application/json');
    Object.entries(extraHeaders).forEach(([key, value]) => {
      request.setHeader(key, value);
    });
    if (appToken) {
      request.setHeader('X-App-Token', appToken);
    }
    if (cookieHeader && !('Cookie' in extraHeaders)) {
      request.setHeader('Cookie', cookieHeader);
    }
    if (sessionObj && typeof sessionObj.getUserAgent === 'function' && !('User-Agent' in extraHeaders)) {
      request.setHeader('User-Agent', sessionObj.getUserAgent());
    }

    const chunks = [];
    request.on('response', (response) => {
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', async () => {
        const raw = Buffer.concat(chunks).toString('utf-8');
        let data = null;
        try {
          data = raw ? JSON.parse(raw) : null;
        } catch (err) {
          data = null;
        }
        try {
          await applySetCookieHeaders(sessionObj, url, response.headers);
        } catch (err) {
          console.log(`[ADMIN] Failed to apply cookies: ${err.message}`);
        }
        resolve({ status: response.statusCode || 0, data, headers: response.headers });
      });
    });
    request.on('error', reject);
    if (body) {
      request.write(JSON.stringify(body));
    }
    request.end();
  });
};

const verifyAdminAccess = async (sessionObj, targetBase, context) => {
  const url = new URL('/admin', targetBase).toString();
  const timestamp = Math.floor(Date.now() / 1000);
  const signature = signPayload('GET', '/admin', timestamp, context.token, context.secret);
  const response = await requestJson(sessionObj, url, 'GET', null, {
    'X-Admin-Token': context.token,
    'X-Admin-Timestamp': `${timestamp}`,
    'X-Admin-Signature': signature
  }, context.appToken);
  return response.status === 200;
};

const createWindow = () => {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 760,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: '#F8FAFC',
    icon: APP_ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
};

const wireAdminHeaders = () => {
  const config = getConfig();
  const appToken = config.appToken;
  const targetOrigin = config.targetOrigin;

  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const url = new URL(details.url);
    if (url.origin !== targetOrigin) {
      callback({ requestHeaders: details.requestHeaders });
      return;
    }

    const headers = {
      ...details.requestHeaders,
    };
    if (appToken) {
      headers['X-App-Token'] = appToken;
    }

    if (adminContext && shouldSignPath(url.pathname)) {
      const timestamp = Math.floor(Date.now() / 1000);
      const signature = signPayload(details.method, url.pathname, timestamp, adminContext.token, adminContext.secret);
      headers['X-Admin-Token'] = adminContext.token;
      headers['X-Admin-Timestamp'] = `${timestamp}`;
      headers['X-Admin-Signature'] = signature;
    }

    callback({ requestHeaders: headers });
  });
};

const safeRealpath = (value) => {
  try {
    return fs.realpathSync.native ? fs.realpathSync.native(value) : fs.realpathSync(value);
  } catch (err) {
    return null;
  }
};

const resolveAppBundlePath = () => {
  let current = app.getAppPath();
  for (let i = 0; i < 6; i += 1) {
    if (current.endsWith('.app')) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  return null;
};

const cleanupDuplicateApps = () => {
  const appBundle = resolveAppBundlePath();
  const appName = `${app.getName()}.app`;
  const roots = [
    '/Applications',
    path.join(os.homedir(), 'Applications'),
    path.join(os.homedir(), 'Downloads'),
    path.join(os.homedir(), 'Desktop'),
    process.cwd()
  ];
  const currentReal = appBundle ? safeRealpath(appBundle) : null;

  roots.forEach((root) => {
    const candidate = path.join(root, appName);
    if (!fs.existsSync(candidate)) {
      return;
    }
    const candidateReal = safeRealpath(candidate);
    if (currentReal && candidateReal && currentReal === candidateReal) {
      return;
    }
    const ok = shell.moveItemToTrash(candidate);
    if (ok) {
      console.log(`[ADMIN] Removed duplicate app bundle: ${candidate}`);
    } else {
      console.log(`[ADMIN] Failed to remove duplicate app bundle: ${candidate}`);
    }
  });
};

ipcMain.handle('admin:get-config', () => {
  const config = getConfig();
  return { targetBase: config.targetBase };
});

ipcMain.handle('admin:login', async (_event, payload) => {
  const { id, password } = payload || {};
  const config = getConfig();
  if (!config.adminToken || !config.adminSecret) {
    setTimeout(() => app.quit(), 800);
    return { ok: false, error: 'Missing admin tokens.' };
  }
  if (!id || !password) {
    setTimeout(() => app.quit(), 800);
    return { ok: false, error: 'Missing credentials.' };
  }

  try {
    const loginResponse = await requestJson(session.defaultSession, `${config.targetBase}/api/auth/login`, 'POST', {
      email: String(id).trim(),
      password: String(password)
    }, {}, config.appToken);

    if (loginResponse.status !== 200 || !loginResponse.data || !loginResponse.data.success) {
      setTimeout(() => app.quit(), 800);
      const errorMessage = loginResponse.data && loginResponse.data.error ? loginResponse.data.error : 'Login failed.';
      return { ok: false, error: errorMessage };
    }

    const email = String(id).trim().toLowerCase();
    adminContext = {
      email,
      token: config.adminToken,
      secret: config.adminSecret,
      appToken: config.appToken
    };

    const isAllowed = await verifyAdminAccess(session.defaultSession, config.targetBase, adminContext);
    if (!isAllowed) {
      setTimeout(() => app.quit(), 800);
      return { ok: false, error: 'Admin access denied.' };
    }

    await mainWindow.loadURL(`${config.targetBase}/admin`);
    return { ok: true };
  } catch (err) {
    setTimeout(() => app.quit(), 800);
    return { ok: false, error: 'Admin login failed.' };
  }
});

ipcMain.handle('admin:quit', () => {
  app.quit();
});

app.whenReady().then(() => {
  loadEnv();
  cleanupDuplicateApps();
  wireAdminHeaders();
  if (process.platform === 'darwin' && app.dock && fs.existsSync(APP_ICON_PATH)) {
    app.dock.setIcon(APP_ICON_PATH);
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
