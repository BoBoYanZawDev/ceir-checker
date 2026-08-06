// CEIR Electron — Full backend (Phases 1–5)
// Activation gate on startup: stored license → verify signature + machine ID
// + expiry (lib/license.js). Missing/invalid → activation window instead of
// the main app. Keys come from ceir-imei-check-admin (same keypair,
// app-specific machine-ID salt).
const { app, BrowserWindow, ipcMain, dialog, clipboard } = require('electron');
const path    = require('path');

// Silence harmless EGL/GPU noise on older Intel Macs and machines without GPU
// acceleration. Must run BEFORE app.whenReady().
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
app.commandLine.appendSwitch('log-level', '3');         // ERROR-only (default is INFO=0)
if (process.platform === 'darwin' && process.arch === 'x64') {
    // Older Intel macs sometimes need software GL to avoid EGL driver spam
    app.disableHardwareAcceleration();
}
const altcha  = require('./altcha');
const excel   = require('./lib/excel');
const config  = require('./lib/config');
const receipt = require('./lib/receipt');
const audit   = require('./lib/audit');
const tac     = require('./lib/tac_cache');
const state   = require('./lib/state_store');
const license = require('./lib/license');
const cloud   = require('./lib/cloud');

const CEIR_BASE = 'https://ceir.gov.mm';

// Present the same User-Agent as plain Chrome — Electron's default UA
// contains "Electron/32.x ceir-tool/1.x" which WAF rules can flag as a bot.
app.userAgentFallback = app.userAgentFallback
    .replace(/\sElectron\/[\d.]+/i, '')
    .replace(/\sceir-tool\/[\d.]+/i, '');

// CEIR (since 2026-07-06) geo-blocks all /openapi/* calls from non-Myanmar
// IPs with an "Access Restricted" HTML page (HTTP 403). A VPN (e.g. Outline)
// with a foreign exit makes every API call fail — detect it and tell the
// user instead of looping on pointless reconnects.
function isGeoBlocked(res) {
    return !!(res && res.ok && res.status === 403 && typeof res.text === 'string' &&
              /Access Restricted|only accessible from Myanmar/i.test(res.text));
}
let lastGeoBlockTs = 0;
// True if a geo-block was seen in the last 15s — batch loops use this to
// abort instead of burning one failed altcha call per row.
function geoActive() { return Date.now() - lastGeoBlockTs < 15000; }
let lastGeoNotifyTs = 0;
function notifyGeoBlocked() {
    if (Date.now() - lastGeoNotifyTs < 30000) return;
    lastGeoNotifyTs = Date.now();
    log('GEO', 'CEIR rejected the request: "only accessible from Myanmar". Turn OFF your VPN (Outline) and reconnect.');
    audit.recordEvent('geo_blocked', {});
    sendMain('geo-blocked', { error: 'CEIR blocks foreign IPs — turn off your VPN and click ↻ Reconnect' });
}

let mainWin       = null;
let activationWin = null;
let loginWin      = null;
let pendingExpiry = null;   // license expiry carried across the login step
let ceirWin       = null;
let bridgeLock    = Promise.resolve();   // serialise concurrent bridgeFetch
let cancelFlags   = {};                  // job_id -> bool

// ── Lifecycle ────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
    cloud.init(app);
    audit.recordEvent('app_start', {
        version: app.getVersion(), platform: process.platform, arch: process.arch,
        electron: process.versions.electron,
    });
    const check = license.checkStoredLicense(app);
    if (check.ok) gateToApp(check.expiresAt);
    else          openActivation();
});

// License OK → require a cloud account session (login like ceir-mobile).
// A persisted session lets the app open offline; no session → login window.
async function gateToApp(expiresAt) {
    pendingExpiry = expiresAt;
    const session = await cloud.getSession();
    if (session) {
        await cloud.loadProfile();
        openMainApp(expiresAt);
    } else {
        openLogin();
    }
}

function openLogin() {
    loginWin = new BrowserWindow({
        width: 480, height: 520,
        resizable: false, minimizable: true, maximizable: false, fullscreenable: false,
        title: 'Sign in — CEIR Tool',
        backgroundColor: '#ecebfa',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
        },
    });
    loginWin.setMenu(null);
    loginWin.loadFile('renderer/login.html');
    loginWin.on('closed', () => { loginWin = null; });
}

function openActivation() {
    activationWin = new BrowserWindow({
        width: 620, height: 620,
        resizable: false, minimizable: true, maximizable: false, fullscreenable: false,
        title: 'Activate CEIR Tool',
        backgroundColor: '#ecebfa',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
        },
    });
    activationWin.setMenu(null);
    activationWin.loadFile('renderer/activation.html');
    activationWin.on('closed', () => { activationWin = null; });
}

function openMainApp(expiresAt) {
    mainWin = new BrowserWindow({
        width: 1380, height: 880,
        title: 'CEIR Tool',
        backgroundColor: '#f5f7fb',
        titleBarStyle: 'hiddenInset',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            sandbox: false,
            webviewTag: true,            // ← enables <webview> for inline Pay Center
        },
    });
    mainWin.loadFile('index.html');
    mainWin.webContents.on('did-finish-load', () => {
        sendMain('license-info', {
            expiresAt,
            machineId: license.getMachineIdFormatted(),
        });
        sendMain('cloud-user', cloud.getProfile());
    });
    mainWin.on('closed', () => { mainWin = null; });

    createCeirWindow();
    startKeepalive();
    startHeartbeat();
}

// ── IPC: Activation ──────────────────────────────────────────────────────────
ipcMain.handle('get-machine-id', () => license.getMachineIdFormatted());

ipcMain.handle('activate', async (_e, code) => {
    const res = license.verifyLicenseCode(code);
    if (!res.ok) return res;
    license.writeStoredLicense(app, code);
    audit.recordEvent('activated', { expiresAt: res.expiresAt });
    // Close activation window, continue to login (or straight in if a session exists)
    if (activationWin && !activationWin.isDestroyed()) activationWin.close();
    gateToApp(res.expiresAt);
    return res;
});

// ── IPC: Cloud account (login/logout like ceir-mobile) ──────────────────────
ipcMain.handle('cloud-login', async (_e, { email, password }) => {
    const res = await cloud.signIn(email, password);
    if (!res.ok) return res;
    audit.recordEvent('login', { email: res.profile?.email || email });
    if (loginWin && !loginWin.isDestroyed()) loginWin.close();
    openMainApp(pendingExpiry);
    return res;
});

ipcMain.handle('cloud-user', () => cloud.getProfile());

ipcMain.handle('cloud-logout', async () => {
    audit.recordEvent('logout', { email: cloud.getProfile()?.email || '' });
    await cloud.signOut();          // flushes the upload queue first
    app.relaunch();                 // clean restart → login window
    app.exit(0);
});

ipcMain.handle('license-info', () => {
    const check = license.checkStoredLicense(app);
    return {
        ok: !!check.ok,
        reason: check.reason || '',
        expiresAt: check.expiresAt || 0,
        machineId: license.getMachineIdFormatted(),
    };
});

ipcMain.handle('copy-to-clipboard', (_e, text) => {
    clipboard.writeText(String(text || ''));
    return true;
});

// Batch operations re-verify the license so an expired key stops the heavy
// features even if the app has been left running past midnight of expiry.
function licenseGate() {
    const check = license.checkStoredLicense(app);
    if (check.ok) return null;
    const msg = check.reason === 'expired'
        ? 'License expired — ask your provider for a renewal key.'
        : 'License invalid — restart the app to re-activate.';
    log('LICENSE', msg);
    return { ok: false, error: msg, license: check.reason || 'invalid' };
}

// Create (or recreate) the hidden CEIR window. Safe to call any time.
function createCeirWindow() {
    if (ceirWin && !ceirWin.isDestroyed()) return ceirWin;
    ceirWin = new BrowserWindow({
        show: false, width: 1000, height: 700,
        webPreferences: { partition: 'persist:ceir' },
    });
    ceirWin.on('closed', () => { ceirWin = null; });
    try { ceirWin.loadURL(CEIR_BASE); }
    catch (e) { log('CF', `loadURL on new window failed: ${e.message}`); }
    return ceirWin;
}

function ceirWinAlive() {
    return ceirWin && !ceirWin.isDestroyed();
}

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});

// Log the quit + push any still-queued cloud rows (max 1.5s, then quit anyway)
// so the last minutes of a work day are not stuck on the machine overnight.
let quitFlushDone = false;
app.on('before-quit', (e) => {
    if (quitFlushDone) return;
    quitFlushDone = true;
    e.preventDefault();
    audit.recordEvent('app_quit', { uptime_min: Math.round(process.uptime() / 60) });
    Promise.race([cloud.flush(), new Promise(r => setTimeout(r, 1500))])
        .catch(() => {})
        .finally(() => app.quit());
});

// Crash visibility: record main-process failures so silent crashes show up in
// the activity log instead of only in the employee's memory.
process.on('uncaughtException', (err) => {
    console.error('[crash]', err);
    try { audit.recordEvent('crash', { kind: 'uncaught', error: String(err && err.message || err), stack: String(err && err.stack || '').slice(0, 1500) }); } catch {}
});
process.on('unhandledRejection', (err) => {
    console.error('[crash] unhandledRejection:', err);
    try { audit.recordEvent('crash', { kind: 'rejection', error: String(err && err.message || err), stack: String(err && err.stack || '').slice(0, 1500) }); } catch {}
});

// ── Helpers ──────────────────────────────────────────────────────────────────
function sendMain(channel, payload) {
    if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send(channel, payload);
}
function log(tag, msg) {
    sendMain('log', { tag, msg });
    console.log(`[${tag}]`, msg);
}

// Track last bridge call latency for the live connection indicator.
let lastBridgeOkTs = 0;
let lastBridgeMs   = 0;

// ── Network capture (debug mode) ─────────────────────────────────────────
// Records ALL network traffic in the CEIR window (website + our bridge
// fetches) to a JSONL file so app requests can be diffed against the real
// website's requests when CEIR changes their API.
let capture = null;   // { file, reqs: Map<requestId, entry>, count, startedAt }

const CAPTURE_SKIP_EXT = /\.(css|js|mjs|png|jpe?g|gif|svg|webp|woff2?|ttf|otf|eot|ico|map|mp4|webm)(\?|$)/i;
const CAPTURE_BODY_MAX = 200 * 1024;

function captureWrite(obj) {
    if (!capture) return;
    try {
        fsMain.appendFileSync(capture.file, JSON.stringify({ ts: new Date().toISOString(), ...obj }) + '\n');
        capture.count++;
    } catch (e) { console.error('[capture] write failed:', e.message); }
}

function captureInteresting(url, type) {
    if (!url || url.startsWith('data:') || url.startsWith('blob:')) return false;
    if (!/ceir\.gov\.mm|ird\.gov\.mm/i.test(url)) return false;
    if (CAPTURE_SKIP_EXT.test(url)) return false;
    return true;
}

async function startCapture() {
    if (capture) return { ok: true, file: capture.file, already: true };
    if (!ceirWinAlive()) createCeirWindow();
    if (!ceirWinAlive()) return { ok: false, error: 'ceir window not available' };
    const dbg = ceirWin.webContents.debugger;
    try {
        if (!dbg.isAttached()) dbg.attach('1.3');
        await dbg.sendCommand('Network.enable', {
            maxTotalBufferSize: 50 * 1024 * 1024,
            maxResourceBufferSize: 10 * 1024 * 1024,
        });
    } catch (e) {
        return { ok: false, error: `debugger attach failed: ${e.message}` };
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    capture = {
        file: path.join(audit.getLogsDir(), `capture_${stamp}.jsonl`),
        reqs: new Map(),
        count: 0,
        startedAt: Date.now(),
    };

    const onMessage = async (_e, method, params) => {
        if (!capture) return;
        try {
            if (method === 'Network.requestWillBeSent') {
                const { requestId, request, type, redirectResponse } = params;
                if (!captureInteresting(request.url, type)) return;
                // A redirect re-uses the requestId — flush the previous hop first.
                if (redirectResponse && capture.reqs.has(requestId)) {
                    const prev = capture.reqs.get(requestId);
                    captureWrite({ source: 'website', event: 'redirect',
                        method: prev.method, url: prev.url, reqHeaders: prev.reqHeaders,
                        postData: prev.postData || null,
                        status: redirectResponse.status, respHeaders: redirectResponse.headers,
                        location: request.url });
                }
                capture.reqs.set(requestId, {
                    method: request.method, url: request.url,
                    reqHeaders: request.headers, postData: request.postData || null,
                    hasPostData: !!request.hasPostData, type: type || '',
                });
            } else if (method === 'Network.requestWillBeSentExtraInfo') {
                // Real wire headers (incl. cookies) arrive here — merge them in.
                const r = capture.reqs.get(params.requestId);
                if (r) r.wireHeaders = params.headers;
            } else if (method === 'Network.responseReceived') {
                const r = capture.reqs.get(params.requestId);
                if (!r) return;
                r.status     = params.response.status;
                r.statusText = params.response.statusText;
                r.respHeaders = params.response.headers;
                r.mimeType   = params.response.mimeType;
            } else if (method === 'Network.loadingFinished') {
                const r = capture.reqs.get(params.requestId);
                if (!r) return;
                capture.reqs.delete(params.requestId);
                // Fill in POST body if CDP didn't inline it
                if (!r.postData && r.hasPostData) {
                    try {
                        const pd = await dbg.sendCommand('Network.getRequestPostData', { requestId: params.requestId });
                        r.postData = pd.postData;
                    } catch (e) {}
                }
                let body = null, bodyTruncated = false, base64 = false;
                try {
                    const rb = await dbg.sendCommand('Network.getResponseBody', { requestId: params.requestId });
                    body = rb.body || '';
                    base64 = !!rb.base64Encoded;
                    if (body.length > CAPTURE_BODY_MAX) { body = body.slice(0, CAPTURE_BODY_MAX); bodyTruncated = true; }
                } catch (e) { body = `<body unavailable: ${e.message}>`; }
                captureWrite({ source: 'website', event: 'response',
                    method: r.method, url: r.url, resourceType: r.type,
                    reqHeaders: r.wireHeaders || r.reqHeaders, postData: r.postData,
                    status: r.status, statusText: r.statusText || '',
                    respHeaders: r.respHeaders, mimeType: r.mimeType,
                    bodyBase64: base64, bodyTruncated, body });
            } else if (method === 'Network.loadingFailed') {
                const r = capture.reqs.get(params.requestId);
                if (!r) return;
                capture.reqs.delete(params.requestId);
                captureWrite({ source: 'website', event: 'failed',
                    method: r.method, url: r.url, resourceType: r.type,
                    reqHeaders: r.wireHeaders || r.reqHeaders, postData: r.postData,
                    error: params.errorText, canceled: !!params.canceled });
            }
        } catch (e) { console.error('[capture] handler error:', e.message); }
    };
    const onDetach = (_e, reason) => {
        if (capture) {
            captureWrite({ source: 'capture', event: 'detached', reason });
            log('CAPTURE', `debugger detached (${reason}) — capture stopped`);
            removeCaptureListeners();
            capture = null;
        }
    };
    capture.listeners = { dbg, onMessage, onDetach };
    dbg.on('message', onMessage);
    dbg.on('detach', onDetach);

    captureWrite({ source: 'capture', event: 'start',
        url: ceirWin.webContents.getURL(), title: ceirWin.webContents.getTitle() });
    ceirWin.show(); ceirWin.focus();
    log('CAPTURE', `Recording all CEIR traffic → ${capture.file}`);
    return { ok: true, file: capture.file };
}

function removeCaptureListeners() {
    const l = capture && capture.listeners;
    if (!l) return;
    try { l.dbg.removeListener('message', l.onMessage); } catch (e) {}
    try { l.dbg.removeListener('detach',  l.onDetach);  } catch (e) {}
}

function stopCapture() {
    if (!capture) return { ok: false, error: 'not capturing' };
    const { file, count } = capture;
    captureWrite({ source: 'capture', event: 'stop', entries: count });
    removeCaptureListeners();
    capture = null;
    try {
        const dbg = ceirWin && !ceirWin.isDestroyed() && ceirWin.webContents.debugger;
        if (dbg && dbg.isAttached()) dbg.detach();
    } catch (e) {}
    log('CAPTURE', `Stopped — ${count} entries → ${file}`);
    return { ok: true, file, count };
}

// Internal serial fetch — single shot, no retry. Used by both the wrapper
// (which adds auto-recover) and the silent reconnect itself.
async function bridgeFetchRaw(url, method = 'GET', body = null, headers = {}) {
    bridgeLock = bridgeLock.then(async () => {
        if (!ceirWinAlive()) {
            // Window got destroyed (user closed main window etc.). Recreate
            // and wait for CF to clear before retrying the call.
            log('CF', 'ceir window was destroyed — recreating…');
            createCeirWindow();
            await waitForCeirReady(45).catch(() => {});
            if (!ceirWinAlive()) return { ok: false, error: 'ceir window not ready' };
        }
        const optsLit = JSON.stringify({
            method, credentials: 'include', headers,
            body: body || undefined,
        });
        const js = `(async () => {
            try {
                const r = await fetch(${JSON.stringify(url)}, ${optsLit});
                const text = await r.text();
                return { ok: true, status: r.status, text };
            } catch (e) { return { ok: false, error: e.message }; }
        })()`;
        const t0 = Date.now();
        let res;
        try { res = await ceirWin.webContents.executeJavaScript(js, true); }
        catch (e) { res = { ok: false, error: e.message }; }
        const dt = Date.now() - t0;
        if (res && res.ok && (res.status || 0) < 500) {
            lastBridgeOkTs = Date.now();
            lastBridgeMs = dt;
        }
        // Capture-mode mirror: tag this as an APP request (the CDP listener
        // also sees it as page traffic — this line marks which ones are ours).
        captureWrite({ source: 'app', event: 'bridge_fetch',
            method, url, headers, postData: body || null,
            status: res && res.status || 0, error: res && res.error || null,
            ms: dt, body: res && typeof res.text === 'string' ? res.text.slice(0, CAPTURE_BODY_MAX) : null });
        // Always-on error trail: any HTTP >= 400 / fetch error goes to the
        // audit log so failures survive even when nobody is watching the UI.
        if (!res || !res.ok || (res.status || 0) >= 400) {
            audit.recordEvent('http_error', {
                method, url,
                status: res && res.status || 0,
                error:  res && res.error  || '',
                request_body: body ? String(body).slice(0, 2000) : '',
                response_text: res && typeof res.text === 'string' ? res.text.slice(0, 2000) : '',
                ms: dt,
            });
        }
        return res;
    });
    return bridgeLock;
}

// Silent reconnect — reload the hidden ceir.gov.mm window (or recreate it if
// destroyed) and wait until CF challenge clears. Throttled to one attempt
// per 8 seconds so we don't loop on persistent errors.
let lastReconnectTs    = 0;
let reconnectInFlight  = null;
function silentReconnect() {
    if (reconnectInFlight) return reconnectInFlight;
    const since = Date.now() - lastReconnectTs;
    if (since < 8000) return Promise.resolve({ ok: false, error: 'throttled' });
    lastReconnectTs = Date.now();
    reconnectInFlight = (async () => {
        try {
            log('CF', 'Auto-reconnect: refreshing ceir.gov.mm…');
            if (!ceirWinAlive()) createCeirWindow();
            if (!ceirWinAlive()) return { ok: false, error: 'cannot create window' };
            try { ceirWin.loadURL(CEIR_BASE); }
            catch (e) { return { ok: false, error: e.message }; }
            const deadline = Date.now() + 25000;
            const cfMarkers = ['just a moment', 'ddos-guard', 'checking your browser', 'please wait'];
            while (Date.now() < deadline) {
                if (!ceirWinAlive()) return { ok: false, error: 'window destroyed mid-reconnect' };
                const title = (ceirWin.webContents.getTitle() || '').toLowerCase();
                const url = ceirWin.webContents.getURL();
                if (title && !cfMarkers.some(m => title.includes(m)) && url.includes('ceir.gov.mm')) {
                    log('CF', `Auto-reconnect ok (${title})`);
                    return { ok: true };
                }
                await new Promise(r => setTimeout(r, 400));
            }
            log('CF', 'Auto-reconnect: still on CF challenge — manual reconnect needed');
            audit.recordEvent('session_expired', { reason: 'cf_challenge_persists' });
            sendMain('session-expired', { error: 'CF challenge persists, manual ↻ Reconnect needed' });
            return { ok: false, error: 'cf challenge persists' };
        } finally {
            reconnectInFlight = null;
        }
    })();
    return reconnectInFlight;
}

// Public wrapper: bridge fetch with automatic recovery.
// Only triggers a silent reconnect on actual API-level failures (403 from
// CEIR, network error from fetch()). We DO NOT recover on "window not
// ready" errors here — bridgeFetchRaw already handles window recreation
// internally, so by the time we get back a network error it's likely a
// real network issue, not a destroyed window.
async function bridgeFetch(url, method = 'GET', body = null, headers = {}) {
    let res = await bridgeFetchRaw(url, method, body, headers);
    // Geo-block 403 is not a session problem — reconnecting can't fix it.
    if (isGeoBlocked(res)) {
        lastGeoBlockTs = Date.now();
        notifyGeoBlocked();
        res.geoBlocked = true;
        return res;
    }
    const looks403   = res && res.ok && res.status === 403;
    const netError   = res && !res.ok && res.error && !/(window not ready|window destroyed)/i.test(res.error);
    if (looks403 || netError) {
        log('CF', `Bridge call returned ${looks403 ? '403' : 'error: ' + res.error} — triggering auto-reconnect`);
        const rec = await silentReconnect();
        if (rec.ok) {
            log('CF', `Retrying original call after reconnect…`);
            res = await bridgeFetchRaw(url, method, body, headers);
        }
    }
    return res;
}

async function waitForCeirReady(timeoutSec = 90) {
    const deadline = Date.now() + timeoutSec * 1000;
    const cfMarkers = ['just a moment', 'ddos-guard', 'checking your browser', 'please wait'];

    if (!ceirWinAlive()) createCeirWindow();
    if (!ceirWinAlive()) return { ok: false, error: 'cannot create window' };

    // Capture load failures while we wait (e.g. DNS failure, TCP refused, TLS error)
    let lastFailure = null;
    const onFail = (_e, errorCode, errorDescription, validatedURL, isMainFrame) => {
        if (!isMainFrame) return;
        if (errorCode === -3) return;            // ABORTED — happens on legitimate reloads, ignore
        lastFailure = { errorCode, errorDescription, validatedURL };
    };
    ceirWin.webContents.on('did-fail-load', onFail);

    let lastReported = '';
    function report(state) {
        if (state === lastReported) return;
        lastReported = state;
        sendMain('cf-progress', { state, ts: Date.now() });
    }

    try {
        report('loading');
        while (Date.now() < deadline) {
            if (!ceirWinAlive()) {
                return { ok: false, error: 'ceir window destroyed mid-wait' };
            }
            if (lastFailure) {
                return { ok: false, error: `Network error: ${lastFailure.errorDescription} (code ${lastFailure.errorCode})`,
                         code: lastFailure.errorCode, title: '', url: lastFailure.validatedURL || '' };
            }
            const title = (ceirWin.webContents.getTitle() || '').toLowerCase();
            const url   = ceirWin.webContents.getURL();
            const isCf  = title && cfMarkers.some(m => title.includes(m));
            const reached = url.includes('ceir.gov.mm');
            if (title.includes('access restricted')) {
                lastGeoBlockTs = Date.now();
                notifyGeoBlocked();
                return { ok: false, geoBlocked: true, title, url,
                         error: 'Geo-blocked: CEIR only allows Myanmar IPs. Turn OFF your VPN (Outline) and reconnect.' };
            }
            if (title && !isCf && reached) {
                report('ready');
                return { ok: true, title, url };
            }
            if (isCf)            report('cf_challenge');
            else if (!reached)   report('loading');
            else if (!title)     report('parsing');
            await new Promise(r => setTimeout(r, 500));
        }
        if (!ceirWinAlive()) return { ok: false, error: 'window destroyed at timeout' };
        return { ok: false,
                 error: `Timed out after ${timeoutSec}s. Check internet + try Reconnect.`,
                 title: ceirWin.webContents.getTitle(), url: ceirWin.webContents.getURL() };
    } finally {
        try { if (ceirWinAlive()) ceirWin.webContents.off('did-fail-load', onFail); }
        catch (e) {}
    }
}

// Resilient altcha token fetch with retries + exponential backoff.
// Most "altcha fetch error" failures are transient — the request lost
// the race with CF refresh, or the PoW seed was malformed once. Retrying
// 3 times turns those into invisible blips.
async function getAltchaToken() {
    const maxAttempts = 3;
    let lastError = '';
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        const res = await bridgeFetch(`${CEIR_BASE}/openapi/API/Auth/altcha/altcha`);
        if (res.ok && res.status === 200) {
            try {
                const challenge = JSON.parse(res.text);
                if (!challenge.challenge) {
                    lastError = `malformed altcha (no challenge field)`;
                } else {
                    const token = await altcha.solve(challenge);
                    if (token) return token;
                    lastError = 'PoW solve returned null';
                }
            } catch (e) {
                lastError = `bad JSON: ${e.message}`;
            }
        } else {
            lastError = res.error || `HTTP ${res.status || '?'}`;
            if (res.geoBlocked) {           // retrying can't fix a geo-block
                log('CF', 'altcha geo-blocked — aborting retries');
                return null;
            }
        }
        if (attempt < maxAttempts) {
            const waitMs = attempt * 800;        // 800ms, 1600ms
            log('CF', `altcha attempt ${attempt}/${maxAttempts} failed (${lastError}), retry in ${waitMs}ms`);
            await new Promise(r => setTimeout(r, waitMs));
        }
    }
    log('CF', `altcha gave up after ${maxAttempts} attempts: ${lastError}`);
    return null;
}

// declarationHash is stable per declaration — remember every one we see so
// fetch-ird-html can skip a whole altcha PoW + RegistrationStatus round-trip.
const decHashCache = new Map();   // decId -> declarationHash

async function fetchRegistrationStatus(decId) {
    const token = await getAltchaToken();
    if (!token) return null;
    const r = await bridgeFetch(
        `${CEIR_BASE}/openapi/API/IMEI/RegistrationStatus?DeclarationID=${encodeURIComponent(decId)}&altcha=${encodeURIComponent(token)}`,
        'GET');
    if (!r.ok || r.status !== 200) return null;
    try {
        const data = JSON.parse(r.text);
        const rs = data.RequestStatus || data;
        const dh = rs && (rs.declarationHash || rs.DeclarationHash);
        if (dh) decHashCache.set(decId, dh);
        return rs;
    } catch (e) { return null; }
}

// ── IPC: session ─────────────────────────────────────────────────────────────
ipcMain.handle('connect', async (_e, opts) => {
    const reload = opts && opts.reload;
    // Ensure the hidden window exists before anything else.
    if (!ceirWinAlive()) {
        log('CF', 'Recreating ceir window…');
        createCeirWindow();
    } else if (reload) {
        log('CF', 'Reloading ceir.gov.mm in hidden window…');
        try { ceirWin.loadURL(CEIR_BASE); }
        catch (e) { log('CF', `loadURL error: ${e.message}`); }
        await new Promise(r => setTimeout(r, 600));
    } else {
        log('CF', 'Connecting to ceir.gov.mm…');
    }
    const r = await waitForCeirReady(config.load().cf_wait_sec);
    log('CF', r.ok ? `Connected — ${r.title}` : `Failed: ${r.error}`);
    audit.recordEvent('connect', { ok: r.ok, title: r.title || '', url: r.url || '', error: r.error || '', reload: !!reload });
    return r;
});

// Diagnose — DNS + HTTPS HEAD + bridge fetch, all in parallel.
// Tells the user exactly what's failing: internet, DNS, CEIR down, or CF blocked.
ipcMain.handle('diagnose', async () => {
    const dns   = require('dns').promises;
    const https = require('https');
    const out = { ts: new Date().toISOString() };

    // 1) DNS
    const t1 = Date.now();
    try {
        const addr = await dns.lookup('ceir.gov.mm');
        out.dns = { ok: true, address: addr.address, family: addr.family, ms: Date.now() - t1 };
    } catch (e) {
        out.dns = { ok: false, error: e.code || e.message, ms: Date.now() - t1 };
    }

    // 2) HTTPS reachability — HEAD ceir.gov.mm (we don't care about body)
    const t2 = Date.now();
    out.https = await new Promise((resolve) => {
        const req = https.request({
            hostname: 'ceir.gov.mm', port: 443, path: '/', method: 'HEAD',
            timeout: 8000,
            headers: { 'User-Agent': 'CEIR-Tool/diagnose' },
        }, (res) => {
            resolve({ ok: true, status: res.statusCode,
                      server: res.headers['server'] || '',
                      cfRay: res.headers['cf-ray'] || '',
                      ms: Date.now() - t2 });
            res.resume();
        });
        req.on('timeout', () => { req.destroy(); resolve({ ok: false, error: 'timeout', ms: Date.now() - t2 }); });
        req.on('error',  (e) => { resolve({ ok: false, error: e.code || e.message, ms: Date.now() - t2 }); });
        req.end();
    });

    // 2b) Egress IP geolocation — CEIR requires a Myanmar IP since 2026-07.
    // If a VPN routes traffic abroad, every API call gets geo-blocked.
    const tGeo = Date.now();
    out.egress = await new Promise((resolve) => {
        const req = https.request({
            hostname: 'ipinfo.io', port: 443, path: '/json', method: 'GET',
            timeout: 6000, headers: { 'User-Agent': 'curl/8' },
        }, (res) => {
            let buf = '';
            res.on('data', (c) => buf += c);
            res.on('end', () => {
                try {
                    const j = JSON.parse(buf);
                    resolve({ ok: true, ip: j.ip, country: j.country, city: j.city, org: j.org, ms: Date.now() - tGeo });
                } catch (e) { resolve({ ok: false, error: 'bad JSON', ms: Date.now() - tGeo }); }
            });
        });
        req.on('timeout', () => { req.destroy(); resolve({ ok: false, error: 'timeout', ms: Date.now() - tGeo }); });
        req.on('error',  (e) => { resolve({ ok: false, error: e.code || e.message, ms: Date.now() - tGeo }); });
        req.end();
    });

    // 3) Bridge altcha (if the bridge is set up)
    const t3 = Date.now();
    if (ceirWin && !ceirWin.isDestroyed()) {
        const r = await bridgeFetch(`${CEIR_BASE}/openapi/API/Auth/altcha/altcha`);
        if (!r.ok)                  out.bridge = { ok: false, error: r.error || 'fetch failed', ms: Date.now() - t3 };
        else if (r.geoBlocked)      out.bridge = { ok: false, geoBlocked: true, error: 'Geo-blocked — CEIR only allows Myanmar IPs (turn off VPN)', ms: Date.now() - t3 };
        else if (r.status === 403)  out.bridge = { ok: false, error: 'HTTP 403 — Cloudflare blocking', ms: Date.now() - t3 };
        else if (r.status !== 200)  out.bridge = { ok: false, error: `HTTP ${r.status}`, ms: Date.now() - t3 };
        else {
            try {
                const ch = JSON.parse(r.text);
                out.bridge = { ok: !!ch.challenge, max: ch.maxnumber, ms: Date.now() - t3 };
            } catch (e) { out.bridge = { ok: false, error: 'bad JSON', ms: Date.now() - t3 }; }
        }
    } else {
        out.bridge = { ok: false, error: 'bridge window not ready' };
    }

    // 4) Current bridge window state
    if (ceirWin && !ceirWin.isDestroyed()) {
        out.bridgeWindow = {
            title: ceirWin.webContents.getTitle(),
            url:   ceirWin.webContents.getURL(),
        };
    }
    out.online = require('os').networkInterfaces ? true : false; // basic node check
    return out;
});

// ── CF session keepalive — pings altcha every 90s through the bridge ───
// bridgeFetch already auto-reconnects on 403 / network error, so this loop
// is now self-healing: if the cookie expires, the very next ping repairs it
// silently. Faster cadence so we catch expiry well before any user-facing
// operation runs.
let keepaliveTimer = null;
function startKeepalive() {
    if (keepaliveTimer) clearInterval(keepaliveTimer);
    keepaliveTimer = setInterval(async () => {
        if (!ceirWin || ceirWin.isDestroyed()) return;
        // bridgeFetch handles its own recovery — we just need to trigger it.
        await bridgeFetch(`${CEIR_BASE}/openapi/API/Auth/altcha/altcha`);
    }, 90 * 1000);
}

// ── Live connection heartbeat ────────────────────────────────────────────
//
//  🌐 Internet — HEAD https://1.1.1.1 every 5s (your network reachability)
//  🔧 API     — last actual bridge-call latency (Verify/Register/etc.)
//
// Both signals never touch the bridge → zero performance impact.
// (We intentionally don't probe ceir.gov.mm directly: CEIR's Cloudflare
// rules block our HEAD requests with a 1xxx error even when the site is
// fully up. We rely on real API call latency instead to gauge CEIR health.)
let lastInternetOkTs = 0, lastInternetMs = 0, lastInternetError = '';
const HEARTBEAT_INTERVAL_MS = 5000;
const REPORT_INTERVAL_MS    = 1000;

function probeHttps(opts, onSuccess, onError) {
    const https = require('https');
    const t0 = Date.now();
    const req = https.request(opts, (res) => {
        onSuccess(Date.now() - t0, res.statusCode);
        res.resume();
    });
    req.on('timeout', () => { req.destroy(); onError('timeout'); });
    req.on('error', (e) => { onError(e.code || e.message); });
    req.end();
}

function startHeartbeat() {
    function probeInternet() {
        probeHttps(
            { hostname: '1.1.1.1', port: 443, path: '/', method: 'HEAD',
              timeout: 3000, headers: { 'User-Agent': 'CEIR-Tool/hb' } },
            (ms) => { lastInternetOkTs = Date.now(); lastInternetMs = ms; lastInternetError = ''; },
            (err) => { lastInternetError = err; }
        );
    }
    probeInternet();
    setInterval(probeInternet, HEARTBEAT_INTERVAL_MS);

    // Usage heartbeat every 30 min while the app is open: makes "active hours"
    // accurate even when idle, and queue length reveals machines that stopped
    // syncing (rows piling up locally = data-control alarm).
    setInterval(() => {
        audit.recordEvent('heartbeat', {
            uptime_min: Math.round(process.uptime() / 60),
            queue: cloud.queueLength(),
        });
    }, 30 * 60 * 1000);

    // Push state to renderer every second
    setInterval(() => {
        const now = Date.now();
        function ageS(ts) { return ts ? (now - ts) / 1000 : null; }
        function healthOf(okTs, err) {
            const a = ageS(okTs);
            if (a !== null && a < 12) return 'ok';
            if (err)                  return 'error';
            return 'stale';
        }
        const bridgeAge = ageS(lastBridgeOkTs);
        let apiHealth;
        if (bridgeAge === null)          apiHealth = 'idle';
        else if (bridgeAge < 60)         apiHealth = 'ok';
        else                             apiHealth = 'idle';

        sendMain('conn-tick', {
            internet: {
                health: healthOf(lastInternetOkTs, lastInternetError),
                ms:     lastInternetMs,
                ageS:   ageS(lastInternetOkTs),
                error:  lastInternetError,
            },
            api: {
                health: apiHealth,
                ms:     lastBridgeMs,
                ageS:   bridgeAge,
            },
        });
    }, REPORT_INTERVAL_MS);
}

// Test API — calls altcha to verify the session is alive
ipcMain.handle('test-api', async () => {
    const res = await bridgeFetch(`${CEIR_BASE}/openapi/API/Auth/altcha/altcha`);
    if (!res.ok)                 return { ok: false, error: res.error || 'fetch failed' };
    if (res.geoBlocked)          return { ok: false, error: 'Geo-blocked: CEIR only allows Myanmar IPs. Turn OFF your VPN and reconnect.' };
    if (res.status === 403)      return { ok: false, error: 'HTTP 403 — Cloudflare blocking. Click Reconnect.' };
    if (res.status !== 200)      return { ok: false, error: `HTTP ${res.status}` };
    try {
        const ch = JSON.parse(res.text);
        if (ch.challenge) return { ok: true, challenge: ch.challenge.slice(0, 20), max: ch.maxnumber };
        return { ok: false, error: 'Unexpected response shape' };
    } catch (e) {
        return { ok: false, error: 'JSON parse failed' };
    }
});
ipcMain.handle('show-ceir-window', () => {
    if (ceirWin && !ceirWin.isDestroyed()) { ceirWin.show(); ceirWin.focus(); }
});

// ── IPC: Network capture ─────────────────────────────────────────────────
ipcMain.handle('capture-start',  () => { audit.recordEvent('capture', { action: 'start' }); return startCapture(); });
ipcMain.handle('capture-stop',   () => { audit.recordEvent('capture', { action: 'stop' });  return stopCapture(); });
ipcMain.handle('capture-status', () => capture
    ? { active: true, file: capture.file, count: capture.count }
    : { active: false });

// ── IPC: Config ──────────────────────────────────────────────────────────────
ipcMain.handle('config-load',     () => config.load());
ipcMain.handle('config-save', (_e, cfg) => {
    // Log WHICH settings changed — never the values.
    try {
        const old = config.load();
        const keys = [...new Set([...Object.keys(old || {}), ...Object.keys(cfg || {})])]
            .filter(k => JSON.stringify(old?.[k]) !== JSON.stringify(cfg?.[k]));
        if (keys.length) audit.recordEvent('config_save', { keys });
    } catch {}
    return config.save(cfg);
});
ipcMain.handle('open-logs-folder', () => { audit.recordEvent('logs_opened', {}); audit.openLogsFolder(); return audit.getLogsDir(); });
ipcMain.handle('get-logs-path',    () => audit.getLogsDir());

// ── State persistence (Tier 1) ────────────────────────────────────────────
// taxResults survives across app launches. Saved on every change from
// renderer; auto-loaded on startup.
ipcMain.handle('state-load', () => state.load());
ipcMain.handle('state-save', (_e, s) => state.save(s));
ipcMain.handle('state-clear', () => { audit.recordEvent('state_clear', {}); return state.clear(); });

// ── Duplicate guard (Tier 1) ──────────────────────────────────────────────
// Returns the set of IMEIs that already have a Declaration ID (today's audit
// log + previous days too — anything within the last 30 days). Renderer
// uses this to warn before re-registering.
ipcMain.handle('imei-history', () => {
    const seen = new Map();         // imei -> {declaration_id, date}
    for (let d = 0; d < 30; d++) {
        const date = new Date(); date.setDate(date.getDate() - d);
        const events = audit.readEvents(date);
        for (const ev of events) {
            if (ev.event !== 'tax_register') continue;
            if (!ev.declaration_id) continue;
            if (ev.imei1 && !seen.has(ev.imei1)) seen.set(ev.imei1, { dec: ev.declaration_id, date: ev.timestamp });
            if (ev.imei2 && !seen.has(ev.imei2)) seen.set(ev.imei2, { dec: ev.declaration_id, date: ev.timestamp });
        }
    }
    // Convert Map → object for IPC
    const out = {};
    for (const [k, v] of seen) out[k] = v;
    return out;
});

// ── Smart resume (Tier 1) ─────────────────────────────────────────────────
// Re-fetches Pay Status for every declaration that was PENDING in saved state.
// Catches the "I paid but forgot to click Mark Paid" + "app crashed after
// payment" cases automatically on launch.
ipcMain.handle('smart-resume-check', async (_e, decIds) => {
    if (!Array.isArray(decIds) || !decIds.length) return [];
    sendMain('smart-resume-progress', { done: 0, total: decIds.length });
    const out = [];
    let done = 0;
    for (const decId of decIds) {
        const rs = await fetchRegistrationStatus(decId);
        const biz = rs ? (rs.BusinessState || rs.businessState || '').toUpperCase() : '';
        out.push({ decId, biz_state: biz || 'UNKNOWN' });
        done++;
        sendMain('smart-resume-progress', { done, total: decIds.length });
        if (!rs && geoActive()) {
            log('GEO', `Smart-resume aborted (${done}/${decIds.length}) — geo-blocked`);
            sendMain('smart-resume-progress', { done: decIds.length, total: decIds.length });
            break;
        }
    }
    return out;
});

// ── #1 Device info enrichment (TAC-cached, optimized) ────────────────────
//
// Fast path: device-info often accepts altcha=null (TAC data is public).
// We try that first. If CEIR rejects it (403/401), we fall back to a single
// PoW-backed call. Either way: no sleep between TACs, no PoW per row.
// Compute a Luhn-valid 15-digit IMEI from a TAC. We need this because
// /Device/personal-device-info validates the IMEI with Luhn (HTTP 412 if not).
function imeiForTac(tac) {
    const base = tac + '000000';  // 8 + 6 = 14 digits
    // Luhn checksum (Mod-10)
    let sum = 0;
    for (let i = 0; i < base.length; i++) {
        let d = parseInt(base[i], 10);
        if ((base.length - i) % 2 === 1) {
            d *= 2;
            if (d > 9) d -= 9;
        }
        sum += d;
    }
    const check = (10 - (sum % 10)) % 10;
    return base + check;
}

// ── IMEI catalog (v5): resolve a phone's model and log every IMEI seen ──────
// The model of a phone is fixed by its TAC (first 8 IMEI digits). We resolve
// TAC → {brand, model} once ever (cached), best-effort — a failed/geo-blocked
// lookup just leaves the model blank (ceir-ops buckets those as "Unknown").
async function resolveModel(imei) {
    const t = String(imei || '').slice(0, 8);
    if (t.length < 8) return { tac: t, brand: '', model: '' };
    const cached = tac.get(t);
    if (cached) return { tac: t, brand: cached.brand || '', model: cached.model || '' };
    try {
        const probe = await bridgeFetch(
            `${CEIR_BASE}/openapi/API/Device/personal-device-info?altcha=null&imei=${imei}`, 'GET');
        if (probe.ok && probe.status === 200) {
            const info = JSON.parse(probe.text || '{}');
            const brand = info.gsmaBrandName || info.gsmaManufacturer || '';
            const model = info.gsmaModelName || '';
            if (brand || model) { tac.set(t, { brand, model }); return { tac: t, brand, model }; }
        }
    } catch (e) { /* best-effort */ }
    return { tac: t, brand: '', model: '' };
}

// ── IMEI catalog — hot path does ZERO network + ZERO duplicate uploads ──────
// noteImeisSeen() logs an imei_seen event ONLY the first time a phone is seen
// for a given source (persisted per machine), so re-checking the same phones
// costs nothing. Model names are NOT resolved here — the TAC (free, from the
// IMEI itself) is logged and a low-priority background worker fills in model
// names when the app is idle, keeping the CEIR connection free for real work.
const fsCat = require('fs');
let seenMap = null;               // imei1 -> { i2, tac, c:bool, r:bool }
let seenSaveTimer = null;
const pendingTacs = new Set();    // TACs awaiting a background model lookup
let batchActive = 0;              // >0 while a check/register/pay op is running

function seenFile() { return path.join(app.getPath('userData'), 'imei-seen.json'); }
function loadSeen() {
    if (seenMap) return seenMap;
    try { seenMap = JSON.parse(fsCat.readFileSync(seenFile(), 'utf8')); } catch { seenMap = {}; }
    if (typeof seenMap !== 'object' || !seenMap) seenMap = {};
    return seenMap;
}
function saveSeenSoon() {
    if (seenSaveTimer) return;
    seenSaveTimer = setTimeout(() => {
        seenSaveTimer = null;
        try { fsCat.writeFileSync(seenFile(), JSON.stringify(seenMap)); } catch {}
    }, 3000);
    if (seenSaveTimer.unref) seenSaveTimer.unref();
}

function noteImeisSeen(devices, source) {
    try {
        const map = loadSeen();
        for (const d of devices) {
            if (!d || !d.imei1) continue;
            const t = String(d.imei1).slice(0, 8);
            const prev = map[d.imei1];
            const flag = source === 'register' ? 'r' : 'c';
            // Emit only when this phone (for this source) is genuinely new.
            if (prev && prev[flag]) continue;
            const cached = tac.get(t);
            audit.recordEvent('imei_seen', {
                imei1: d.imei1,
                imei2: d.imei2 || '',
                tac: t,
                brand: cached ? cached.brand || '' : '',
                model: cached ? cached.model || '' : '',
                source,
            });
            map[d.imei1] = { i2: d.imei2 || '', tac: t, c: (prev && prev.c) || flag === 'c', r: (prev && prev.r) || flag === 'r' };
            if (t.length === 8 && !cached) pendingTacs.add(t + '|' + d.imei1);  // keep a real IMEI for the lookup
        }
        saveSeenSoon();
    } catch (e) { console.error('[imei_seen] note failed:', e.message); }
}

// Background model resolver: one TAC at a time, only when nothing else is using
// the CEIR connection and we're online. Logs a `tac_model` event once per TAC.
setInterval(async () => {
    if (batchActive > 0 || !pendingTacs.has) return;
    if (pendingTacs.size === 0) return;
    if (geoActive()) return;                       // VPN/geo problem — try later
    if (Date.now() - lastInternetOkTs > 15000) return;  // offline — try later
    const entry = pendingTacs.values().next().value;
    pendingTacs.delete(entry);
    const [t, sampleImei] = entry.split('|');
    if (tac.get(t)) return;                        // already resolved elsewhere
    try {
        const m = await resolveModel(sampleImei);
        if (m.brand || m.model) audit.recordEvent('tac_model', { tac: t, brand: m.brand, model: m.model });
    } catch (e) { /* try again next cycle if re-added */ }
}, 5000);

// Manual cache reset — useful if previous bad entries got saved
ipcMain.handle('clear-tac-cache', () => { audit.recordEvent('tac_cache_clear', {}); tac.clear(); return { ok: true }; });

ipcMain.handle('enrich-tacs', async (_e, payload) => {
    // payload can be: array of TACs (legacy), or { tacs, tacImeiMap }.
    // tacImeiMap[tac] = real IMEI from user's data — guaranteed Luhn-valid.
    let tacs, tacImeiMap;
    if (Array.isArray(payload)) { tacs = payload; tacImeiMap = {}; }
    else                        { tacs = payload.tacs || []; tacImeiMap = payload.tacImeiMap || {}; }

    function imeiFor(t) {
        return tacImeiMap[t] || imeiForTac(t);
    }

    const out = {};
    const toFetch = [];
    for (const t of tacs) {
        const cached = tac.get(t);
        if (cached) out[t] = cached;
        else toFetch.push(t);
    }
    if (!toFetch.length) return out;
    sendMain('enrich-progress', { done: 0, total: toFetch.length });

    // Helper: parse the device-info response and build the entry
    function parseDeviceInfo(text) {
        try {
            const info = JSON.parse(text || '{}');
            if (!info.gsmaBrandName && !info.gsmaModelName && !info.gsmaManufacturer) {
                return null;     // empty payload = endpoint didn't return data
            }
            return {
                brand: info.gsmaBrandName || info.gsmaManufacturer || '',
                model: info.gsmaModelName || '',
                deviceType: info.gsmaDeviceType || '',
                os:    info.gsmaOperatingSystem || '',
            };
        } catch (e) { return null; }
    }

    // Probe once: try altcha=null with a real Luhn-valid IMEI. If that returns
    // empty/412/500, fall back to per-TAC PoW. We verify the *content*.
    let useNoAltcha = false;
    {
        const probeImei = imeiFor(toFetch[0]);
        const probe = await bridgeFetch(
            `${CEIR_BASE}/openapi/API/Device/personal-device-info?altcha=null&imei=${probeImei}`,
            'GET');
        if (probe.ok && probe.status === 200) {
            const parsed = parseDeviceInfo(probe.text);
            if (parsed) {
                useNoAltcha = true;
                log('CF', `Device info: altcha=null works (fast path)`);
                tac.set(toFetch[0], parsed);
                out[toFetch[0]] = parsed;
                toFetch.shift();         // already done
            } else {
                log('CF', `Device info: altcha=null returned empty — using PoW path`);
            }
        } else {
            log('CF', `Device info probe failed (HTTP ${probe.status || probe.error}) — using PoW path`);
        }
    }

    let done = useNoAltcha && Object.keys(out).length ? 1 : 0;
    const total = done + toFetch.length;
    sendMain('enrich-progress', { done, total });

    for (const t of toFetch) {
        const probeImei = imeiFor(t);
        let url;
        if (useNoAltcha) {
            url = `${CEIR_BASE}/openapi/API/Device/personal-device-info?altcha=null&imei=${probeImei}`;
        } else {
            // PoW path — solve altcha per TAC (CEIR token is one-shot)
            const token = await getAltchaToken();
            if (!token) {
                log('CF', `Device info: altcha solve failed for TAC ${t}`);
                out[t] = null; done++; sendMain('enrich-progress', { done, total });
                if (geoActive()) { log('GEO', 'Enrichment aborted — geo-blocked'); break; }
                continue;
            }
            url = `${CEIR_BASE}/openapi/API/Device/personal-device-info?altcha=${encodeURIComponent(token)}&imei=${probeImei}`;
        }
        const r = await bridgeFetch(url, 'GET');
        if (r.ok && r.status === 200) {
            const entry = parseDeviceInfo(r.text);
            if (entry) {
                tac.set(t, entry);
                out[t] = entry;
            } else {
                log('CF', `Device info empty for TAC ${t} (IMEI ${probeImei}): ${(r.text || '').slice(0, 120)}`);
                out[t] = null;
            }
        } else {
            log('CF', `Device info HTTP ${r.status || '?'} for TAC ${t} (IMEI ${probeImei}): ${r.error || ''}`);
            out[t] = null;
        }
        done++;
        sendMain('enrich-progress', { done, total });
    }
    return out;
});

// ── #6 Lookup by Declaration ID ───────────────────────────────────────────
ipcMain.handle('lookup-declaration', async (_e, decId) => {
    if (!decId) return { ok: false, error: 'no declaration id' };
    const rs = await fetchRegistrationStatus(decId);
    audit.recordEvent('lookup', { declaration_id: decId, ok: !!rs });
    if (!rs) return { ok: false, error: 'not found or fetch failed' };
    const calcs = {};
    for (const c of (rs.orderCalculation && rs.orderCalculation.collectingCalculations) || []) {
        if (c.conditionPassed) calcs[c.collectingType] = c.amount;
    }
    const devices = rs.devices || [];
    const firstDev = devices[0] || {};
    const imeis = firstDev.imeis || [];
    return {
        ok: true,
        row: {
            declaration_id: decId,
            imei1: imeis[0] || '',
            imei2: imeis[1] || null,
            brand: firstDev.brand || '',
            model: firstDev.model || '',
            amount:     rs.amount || 0,
            customs:    calcs.CUSTOMS_DUTY    || 0,
            commercial: calcs.COMMERCIAL_TAX  || 0,
            fine:       calcs.REDEMPTION_FINE || 0,
            status: 'OK',
            pay_status: (rs.BusinessState || rs.businessState || '').toUpperCase() || 'PENDING',
            print_flag: true,
        },
    };
});

// ── #8 Resume — read today's audit log, return registered declarations ───
ipcMain.handle('audit-today-declarations', async () => {
    const events = audit.readEvents(new Date());
    // Build a map of declaration_id → latest known state
    const byDec = {};
    for (const ev of events) {
        if (ev.event === 'tax_register' && ev.declaration_id) {
            byDec[ev.declaration_id] = {
                declaration_id: ev.declaration_id,
                imei1: ev.imei1 || '',
                imei2: ev.imei2 || null,
                amount: ev.amount || 0,
                customs: ev.customs || 0,
                commercial: ev.commercial || 0,
                fine: ev.fine || 0,
                status: ev.status || 'OK',
                pay_status: byDec[ev.declaration_id]?.pay_status || 'PENDING',
                print_flag: true,
            };
        }
        if (ev.event === 'payment' && ev.declaration_id && ev.new_status === 'PAID') {
            if (byDec[ev.declaration_id]) byDec[ev.declaration_id].pay_status = 'PAID';
        }
    }
    return Object.values(byDec);
});

// ── #10 Daily stats ───────────────────────────────────────────────────────
ipcMain.handle('daily-stats', async (_e, days = 7) => {
    return audit.dailyStats(days);
});

// List CUPS printers + auto-detect a Brother QL
ipcMain.handle('list-printers', async () => {
    const list = await receipt.listCupsPrinters();
    let detected = null;
    for (const p of list) {
        const lc = p.toLowerCase();
        if (lc.includes('ql') && (lc.includes('820') || lc.includes('brother'))) { detected = p; break; }
    }
    if (!detected) {
        for (const p of list) if (p.toLowerCase().includes('brother')) { detected = p; break; }
    }
    return { ok: true, printers: list, detected };
});

// ── IPC: IMEI parsing + Excel ────────────────────────────────────────────────
ipcMain.handle('parse-imei-text', (_e, text) => excel.parseImeiText(text));

ipcMain.handle('imei-import-dialog', async () => {
    const r = await dialog.showOpenDialog(mainWin, {
        title: 'Load IMEI File',
        filters: [{ name: 'IMEI files', extensions: ['xlsx','csv','txt'] }],
        properties: ['openFile'],
    });
    if (r.canceled || !r.filePaths[0]) return { ok: false };
    try {
        const pairs = await excel.importImeiFile(r.filePaths[0]);
        audit.recordEvent('file_import', { kind: 'imei', qty: pairs.length });
        return { ok: true, pairs, path: r.filePaths[0] };
    } catch (e) { return { ok: false, error: e.message }; }
});
ipcMain.handle('imei-export-dialog', async (_e, { results, label }) => {
    const r = await dialog.showSaveDialog(mainWin, {
        title: 'Save IMEI Results',
        defaultPath: `${(label || 'ceir_results')}_result.xlsx`,
        filters: [{ name: 'Excel', extensions: ['xlsx'] }],
    });
    if (r.canceled || !r.filePath) return { ok: false };
    try {
        await excel.exportImeiResults(r.filePath, results, label || 'ceir_results');
        audit.recordEvent('file_export', { kind: 'imei_results', qty: (results || []).length });
        return { ok: true, path: r.filePath };
    }
    catch (e) { return { ok: false, error: e.message }; }
});
ipcMain.handle('imei-export-fail-list', async (_e, results) => {
    const r = await dialog.showSaveDialog(mainWin, {
        title: 'Save Fail List', defaultPath: 'ceir_fail.txt',
        filters: [{ name: 'Text', extensions: ['txt'] }],
    });
    if (r.canceled || !r.filePath) return { ok: false };
    try {
        const n = excel.exportFailList(r.filePath, results);
        audit.recordEvent('file_export', { kind: 'fail_list', qty: n });
        return { ok: true, path: r.filePath, count: n };
    }
    catch (e) { return { ok: false, error: e.message }; }
});
ipcMain.handle('tax-export-dialog', async (_e, results) => {
    const r = await dialog.showSaveDialog(mainWin, {
        title: 'Save Tax Results', defaultPath: 'ceir_tax_results.xlsx',
        filters: [{ name: 'Excel', extensions: ['xlsx'] }],
    });
    if (r.canceled || !r.filePath) return { ok: false };
    try {
        await excel.exportTaxResults(r.filePath, results);
        audit.recordEvent('file_export', { kind: 'tax_results', qty: (results || []).length });
        return { ok: true, path: r.filePath };
    }
    catch (e) { return { ok: false, error: e.message }; }
});
ipcMain.handle('tax-import-dialog', async () => {
    const r = await dialog.showOpenDialog(mainWin, {
        title: 'Import Tax Excel', filters: [{ name:'Excel', extensions:['xlsx'] }],
        properties: ['openFile'],
    });
    if (r.canceled || !r.filePaths[0]) return { ok: false };
    try {
        const results = await excel.importTaxResults(r.filePaths[0]);
        audit.recordEvent('file_import', { kind: 'tax_results', qty: (results || []).length });
        return { ok: true, results, path: r.filePaths[0] };
    }
    catch (e) { return { ok: false, error: e.message }; }
});

// ── IPC: IMEI Verify (batched + progress) ────────────────────────────────────
ipcMain.handle('verify-cancel', () => { cancelFlags.verify = true; audit.recordEvent('batch_cancel', { kind: 'verify' }); log('VERIFY','Cancel requested'); });
ipcMain.handle('verify-batch', async (_e, { pairs, batchSize = 5, delayMs = 2000 }) => {
    const gate = licenseGate();
    if (gate) { sendMain('verify-done', { total: 0 }); return gate; }
    cancelFlags.verify = false;
    batchActive++;   // pause background model lookups while the customer works
    const total = pairs.length;
    let done = 0;
    const stat = { phones: 0, paid: 0, unpaid: 0, failed: 0 };   // for the imei_check audit event
try {
    for (let i = 0; i < total; i += batchSize) {
        if (cancelFlags.verify) { log('VERIFY','Stopped.'); break; }
        const batch = pairs.slice(i, i + batchSize);
        const imeis = []; batch.forEach(p => { imeis.push(p.imei1); if (p.imei2) imeis.push(p.imei2); });
        log('VERIFY', `[${done+1}–${done+batch.length}/${total}] ${imeis.length} IMEIs…`);

        const token = await getAltchaToken();
        const batchResults = [];
        if (!token) {
            for (const p of batch) {
                batchResults.push({ imei1: p.imei1, imei2: p.imei2 || '',
                    payment1:'FAILED', payment2: p.imei2 ? 'FAILED' : '',
                    blockState:'', status:'FAILED' });
            }
        } else {
            const verify = await bridgeFetch(
                `${CEIR_BASE}/openapi/API/IMEI/Verify?altcha=${encodeURIComponent(token)}`,
                'POST', JSON.stringify(imeis), { 'Content-Type': 'application/json' });
            let data = null;
            if (verify.ok && verify.status === 200) {
                try { data = JSON.parse(verify.text); } catch (e) {}
            }
            const lookup = {};
            (data && data.IMEI_CHECK_LIST || []).forEach(it => lookup[it.IMEI] = it);
            for (const p of batch) {
                const r1 = lookup[p.imei1], r2 = p.imei2 ? lookup[p.imei2] : null;
                const p1 = r1 ? r1.paymentState : 'FAILED';
                const p2 = p.imei2 ? (r2 ? r2.paymentState : 'FAILED') : '';
                const b1 = r1 ? r1.blockState   : '';
                const b2 = p.imei2 ? (r2 ? r2.blockState : '') : '';
                const bs = p.imei2
                    ? (b1==='UNBLOCKED' && b2==='UNBLOCKED' ? 'UNBLOCKED' : `${b1}/${b2}`) : b1;
                batchResults.push({ imei1: p.imei1, imei2: p.imei2 || '',
                    payment1: p1, payment2: p2, blockState: bs,
                    status: r1 && (!p.imei2 || r2) ? 'OK' : 'FAILED' });
            }
        }
        done += batch.length;
        for (const r of batchResults) {
            for (const st of [r.payment1, r.payment2]) {
                if (!st) continue;
                stat.phones += 1;
                if (st === 'PAID') stat.paid += 1;
                else if (st === 'UNPAID') stat.unpaid += 1;
                else if (st === 'FAILED') stat.failed += 1;
            }
        }
        sendMain('verify-progress', { done, total, batchResults });
        if (i + batchSize < total && !cancelFlags.verify) await new Promise(r => setTimeout(r, delayMs));
    }
    if (done > 0) {
        audit.recordEvent('imei_check', {
            qty: done, ...stat, cancelled: !!cancelFlags.verify,
        });
        // Catalog every checked IMEI (no network, deduped — model filled later).
        noteImeisSeen(pairs.slice(0, done).map(p => ({ imei1: p.imei1, imei2: p.imei2 })), 'check');
    }
    sendMain('verify-done', { total: done });
    return { ok: true, total: done };
} finally { batchActive--; }
});

// ── IPC: Tax Register ────────────────────────────────────────────────────────
ipcMain.handle('tax-cancel', () => { cancelFlags.tax = true; audit.recordEvent('batch_cancel', { kind: 'tax' }); log('TAX','Cancel requested'); });

ipcMain.handle('tax-register-batch', async (_e, { pairs, applicant, delayMs = 3000, skipDuplicates = true }) => {
    const gate = licenseGate();
    if (gate) { sendMain('tax-done', { total: 0 }); return gate; }
    batchActive++;   // pause background model lookups while registering
    try {

    // ── Credit gate (customer accounts only; same rules as ceir-mobile) ──
    // One pair (imei1[+imei2]) = one phone = one consume_credit call, made
    // AFTER a successful registration, keyed by Declaration ID (idempotent).
    const isCustomer = cloud.getProfile()?.kind === 'customer';
    let creditCost = 0;
    if (isCustomer) {
        const ci = await cloud.creditInfo();
        if (!ci.ok) {
            const msg = 'Cannot check credit balance — internet connection is required. (' + ci.error + ')';
            log('CREDIT', msg);
            sendMain('tax-done', { total: 0 });
            return { ok: false, error: msg };
        }
        creditCost = ci.cost;
        const needed = ci.cost * pairs.length;
        if (ci.balance < ci.cost) {
            const msg = `Not enough credits: balance ${ci.balance}, need ${ci.cost} per phone (${needed} for all ${pairs.length}). Top up to continue.`;
            log('CREDIT', msg);
            sendMain('tax-done', { total: 0 });
            return { ok: false, error: msg, credit: 'insufficient' };
        }
        if (ci.balance < needed) {
            log('CREDIT', `Balance ${ci.balance} covers only ${Math.floor(ci.balance / ci.cost)} of ${pairs.length} phones — will stop when credits run out.`);
        }
    }

    cancelFlags.tax = false;
    const total = pairs.length;
    const registered = [];

    // ── Duplicate guard ──────────────────────────────────────────────────
    // Skip IMEIs that already have a Declaration ID in the recent audit log.
    // Avoids double-registering = double-charging the same phone.
    let knownDecls = {};
    if (skipDuplicates) {
        for (let d = 0; d < 30; d++) {
            const date = new Date(); date.setDate(date.getDate() - d);
            const events = audit.readEvents(date);
            for (const ev of events) {
                if (ev.event !== 'tax_register' || !ev.declaration_id) continue;
                if (ev.imei1) knownDecls[ev.imei1] = ev.declaration_id;
                if (ev.imei2) knownDecls[ev.imei2] = ev.declaration_id;
            }
        }
    }

    for (let idx = 0; idx < total; idx++) {
        if (cancelFlags.tax) { log('TAX','Stopped.'); break; }
        const { imei1, imei2 } = pairs[idx];

        // Duplicate check — if either IMEI already has a Declaration ID, skip.
        const existing = knownDecls[imei1] || (imei2 && knownDecls[imei2]);
        if (existing) {
            log('TAX', `[${idx+1}/${total}] SKIP duplicate ${imei1} → already registered as ${existing}`);
            const dup = {
                imei1, imei2: imei2 || '',
                declaration_id: existing,
                amount: 0, customs: 0, commercial: 0, fine: 0,
                status: 'DUPLICATE', pay_status: 'PENDING', print_flag: true,
            };
            audit.recordEvent('duplicate_skip', {
                imei1, imei2: imei2 || '', existing_declaration_id: existing,
            });
            registered.push(dup);
            sendMain('tax-progress', { idx: idx+1, total, result: dup });
            continue;
        }
        log('TAX', `[${idx+1}/${total}] Registering ${imei1}…`);

        // Smart retry: altcha + RegistrationRequest can fail transiently. Retry
        // up to 3 times with exponential backoff (1s, 3s, 7s).
        let token = null, res = null, body = null;
        const maxAttempts = 3;
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            token = await getAltchaToken();
            if (!token) {
                if (attempt < maxAttempts) {
                    const wait = attempt * attempt * 1000;
                    log('TAX', `[${idx+1}] altcha failed, retry ${attempt}/${maxAttempts} in ${wait}ms…`);
                    await new Promise(r => setTimeout(r, wait));
                    continue;
                }
                break;
            }
            body = JSON.stringify({
                imeisList: [{ imeis: imei2 ? [imei1, imei2] : [imei1] }],
                applicant: {
                    id: null, requestId: null,
                    taxpayerType: 'Individual', isForeigner: false, tin: null,
                    ...applicant,
                    regionCode: null, townshipCode: null, uin: null,
                },
            });
            res = await bridgeFetch(
                `${CEIR_BASE}/openapi/API/IMEI/RegistrationRequest?source=LEGAL_INDIVIDUAL&altcha=${encodeURIComponent(token)}`,
                'POST', body, { 'Content-Type': 'application/json' });
            // Retry on transient HTTP errors (5xx, 403, fetch error). Not on 2xx/4xx that are real responses.
            const transient = !res.ok || res.status === 403 || (res.status >= 500 && res.status < 600);
            if (!transient) break;
            if (attempt < maxAttempts) {
                const wait = attempt * attempt * 1000;
                log('TAX', `[${idx+1}] HTTP ${res.status || res.error}, retry ${attempt}/${maxAttempts} in ${wait}ms…`);
                await new Promise(r => setTimeout(r, wait));
            }
        }
        if (!token || !res) {
            const r = { imei1, imei2: imei2 || '', declaration_id:'', amount:0, customs:0, commercial:0, fine:0,
                        status:'ERROR: altcha failed', pay_status:'', print_flag: true };
            audit.recordTaxRegister({
                imei1, imei2: imei2 || '', request_body: body || '', http_status: 0, response_text: '',
                declaration_id: '', amount: 0, customs: 0, commercial: 0, fine: 0,
                status: 'ERROR: altcha failed', error: 'altcha solve failed after retries',
            });
            registered.push(r);
            sendMain('tax-progress', { idx: idx+1, total, result: r });
            if (geoActive()) { log('GEO', 'Tax register aborted — geo-blocked. Turn off VPN and retry.'); break; }
            continue;
        }
        let row;
        let parseError = null;
        try {
            const data = JSON.parse(res.text || '{}');
            if (data.HasError || !data.Registry) {
                row = { imei1, imei2: imei2 || '', declaration_id:'', amount:0, customs:0, commercial:0, fine:0,
                        status: `API Error: ${(data.Message || data.message || 'unknown').slice(0,60)}`,
                        pay_status:'', print_flag: true };
            } else {
                const reg = data.Registry;
                const calcs = {};
                for (const c of (reg.orderCalculation && reg.orderCalculation.collectingCalculations) || []) {
                    if (c.conditionPassed) calcs[c.collectingType] = c.amount;
                }
                row = {
                    imei1, imei2: imei2 || '',
                    declaration_id: reg.DeclarationID || '',
                    amount:     reg.amount || 0,
                    customs:    calcs.CUSTOMS_DUTY    || 0,
                    commercial: calcs.COMMERCIAL_TAX  || 0,
                    fine:       calcs.REDEMPTION_FINE || 0,
                    status: 'OK', pay_status: 'PENDING', print_flag: true,
                };
                log('TAX', `[${idx+1}/${total}] ✓ ${row.declaration_id}  ${row.amount.toLocaleString()} MMK`);
            }
        } catch (e) {
            parseError = e.message;
            row = { imei1, imei2: imei2 || '', declaration_id:'', amount:0, customs:0, commercial:0, fine:0,
                    status: `Bad JSON`, pay_status:'', print_flag: true };
        }
        // Audit log — every attempt, success or fail
        audit.recordTaxRegister({
            imei1, imei2: imei2 || '',
            request_body: body,
            http_status:  res.status || 0,
            response_text: (res.text || '').slice(0, 4000),
            declaration_id: row.declaration_id || '',
            amount:     row.amount     || 0,
            customs:    row.customs    || 0,
            commercial: row.commercial || 0,
            fine:       row.fine       || 0,
            status: row.status,
            error: parseError || res.error || '',
        });
        registered.push(row);
        sendMain('tax-progress', { idx: idx+1, total, result: row });

        // Charge the customer for this phone (idempotent by Declaration ID).
        if (isCustomer && row.status === 'OK' && row.declaration_id) {
            const c = await cloud.consumeCredit(row.declaration_id, row.imei1);
            if (c.ok) {
                sendMain('credit-balance', { balance: c.balance });
                audit.recordEvent('credit_consume', { declaration_id: row.declaration_id, cost: creditCost, balance: c.balance });
                if (c.balance < creditCost && idx + 1 < total) {
                    log('CREDIT', `Out of credits (balance ${c.balance}) — stopping. ${total - idx - 1} phones left unregistered.`);
                    sendMain('credit-exhausted', { balance: c.balance, remaining: total - idx - 1 });
                    break;
                }
            } else if (c.reason === 'insufficient') {
                // Registration succeeded but charging failed — record it so ops
                // can reconcile, then stop the batch.
                audit.recordEvent('credit_consume_failed', { declaration_id: row.declaration_id, reason: c.reason, error: c.error });
                log('CREDIT', `Charge failed for ${row.declaration_id}: ${c.error} — stopping.`);
                sendMain('credit-exhausted', { balance: 0, remaining: total - idx - 1 });
                break;
            } else {
                // Network blip mid-batch: registration stands, charge is only
                // deferred (consume is idempotent — ops reconciles from logs).
                audit.recordEvent('credit_consume_failed', { declaration_id: row.declaration_id, reason: c.reason, error: c.error });
                log('CREDIT', `Charge for ${row.declaration_id} failed (${c.error}) — continuing, will be reconciled.`);
            }
        }
        if (idx + 1 < total && !cancelFlags.tax) await new Promise(r => setTimeout(r, delayMs));
    }
    // Add every registered phone to the IMEI catalog (source = register).
    noteImeisSeen(
        registered.filter(r => r.imei1 && (r.status === 'OK' || r.status === 'DUPLICATE'))
                  .map(r => ({ imei1: r.imei1, imei2: r.imei2 })),
        'register');
    sendMain('tax-done', { total: registered.length });
    return { ok: true, registered };
    } finally { batchActive--; }
});

// ── IPC: prepaid credits (customer accounts) ─────────────────────────────────
ipcMain.handle('credit-info', () => cloud.creditInfo());

ipcMain.handle('check-payment', async (_e, decId) => {
    const rs = await fetchRegistrationStatus(decId);
    const biz = rs ? (rs.BusinessState || rs.businessState || '').toUpperCase() : '';
    audit.recordPayment({
        declaration_id: decId,
        new_status: biz,
        source: 'check_payment',
        error: rs ? '' : 'no RegistrationStatus',
    });
    return { ok: !!rs, biz_state: biz, rs: rs || null };
});

ipcMain.handle('refetch-details', async (_e, rows) => {
    const out = [];
    for (let i = 0; i < rows.length; i++) {
        const { row, decId } = rows[i];
        sendMain('refetch-progress', { done: i, total: rows.length });
        const rs = await fetchRegistrationStatus(decId);
        if (rs) {
            const calcs = {};
            for (const c of (rs.orderCalculation && rs.orderCalculation.collectingCalculations) || []) {
                if (c.conditionPassed) calcs[c.collectingType] = c.amount;
            }
            out.push({
                row,
                fine:       calcs.REDEMPTION_FINE || 0,
                customs:    calcs.CUSTOMS_DUTY    || 0,
                amount:     rs.amount || 0,
                biz_state: (rs.BusinessState || rs.businessState || '').toUpperCase(),
            });
        } else {
            out.push({ row, error: 'fetch failed' });
            if (geoActive()) { log('GEO', 'Re-fetch aborted — geo-blocked'); break; }
        }
        await new Promise(r => setTimeout(r, 800));
    }
    sendMain('refetch-progress', { done: rows.length, total: rows.length });
    audit.recordEvent('refetch_details', { qty: rows.length, ok: out.filter(o => !o.error).length });
    return out;
});

// ── IPC: IRD HTML fetch (for Pay Center / Pay Next) ──────────────────────────
// Returns a file:// URL pointing to the IRD form HTML written to a temp file.
// We use a file URL (not srcdoc/data URL) because the form auto-submits to
// onlinepayment.ird.gov.mm — iframe srcdoc/data: origins block that POST.
const os = require('os');
const fsMain = require('fs');

// Only one IRD chain runs at a time: each page needs several upstream calls
// (altcha PoW, warm-up, applicant, phub/payment) and CEIR answers 400 when
// chains overlap or hammer it. Duplicate requests for the same declaration
// piggyback on the already-running promise instead of starting a second chain.
const irdInFlight = new Map();          // decId -> Promise
let   irdChainLock = Promise.resolve();

// This chain mirrors the real ceir.gov.mm payment flow (verified against a
// Capture-mode recording of a successful website payment on 2026-07-07):
//   GET applicant → POST applicant (confirm) → POST phub/payment.
// The POST request/applicant step is mandatory — the website always re-submits
// the applicant right before phub/payment, and skipping it makes phub/payment
// answer 400 "Payment Hub send payment error". The website does NOT call
// payment-check-result before paying, so the old "warm-up" request is gone.
async function fetchIrdHtmlOnce(decId) {
    // 1) Get declarationHash via RegistrationStatus
    const rs = await fetchRegistrationStatus(decId);
    const dh = rs && (rs.declarationHash || rs.DeclarationHash);
    if (!dh) return { ok: false, error: 'no declarationHash' };

    // 2) Fresh altcha for phub/payment
    const token = await getAltchaToken();
    if (!token) return { ok: false, error: 'altcha failed' };

    // 3) Warm-up
    await bridgeFetch(`${CEIR_BASE}/openapi/API/phub/payment-check-result?declarationHash=${dh}&altcha=null`);

    // 4) applicant payload
    const applRes = await bridgeFetch(`${CEIR_BASE}/openapi/API/request/applicant?declarationHash=${dh}&altcha=null`);
    if (!applRes.ok) return { ok: false, error: 'applicant fetch failed' };
    const applicantBody = applRes.text || '{}';

    // 5) phub/payment → returns IRD form HTML
    const payRes = await bridgeFetch(
        `${CEIR_BASE}/openapi/API/phub/payment?declarationHash=${dh}&altcha=${encodeURIComponent(token)}`,
        'POST', applicantBody, { 'Content-Type': 'application/json' });
    if (!payRes.ok || (payRes.text || '').trim().length < 20) {
        return { ok: false, error: 'phub/payment empty' };
    }

    // Write HTML to temp file. Inject <base href> + desktop viewport so the
    // IRD site renders at full desktop width inside our embedded webview.
    let html = payRes.text;
    const inject = `<base href="https://ceir.gov.mm/"><meta name="viewport" content="width=1280">`;
    if (/<head[^>]*>/i.test(html)) {
        html = html.replace(/<head[^>]*>/i, `$&${inject}`);
    } else {
        html = inject + html;
    }
    try {
        const tmpFile = path.join(os.tmpdir(), `ceir_ird_${decId}_${Date.now()}.html`);
        fsMain.writeFileSync(tmpFile, html, 'utf8');
        return { ok: true, url: `file://${tmpFile}`, html: payRes.text, dec_hash: dh };
    } catch (e) {
        return { ok: false, error: 'tmp file write: ' + e.message };
    }
}


ipcMain.handle('fetch-ird-html', (_e, decId) => {
    if (irdInFlight.has(decId)) return irdInFlight.get(decId);
    batchActive++;   // pause background model lookups while a page is fetched
    const run = irdChainLock
        .then(() => fetchIrdHtmlOnce(decId))
        // pay_open = a Pay Center user started paying this declaration
        .then(r => { audit.recordEvent('pay_open', { declaration_id: decId, ok: !!r.ok, error: r.error || '' }); return r; })
        .catch(e => ({ ok: false, error: e.message }));
    irdChainLock = run;                       // next chain waits — never rejects
    const p = run.finally(() => { irdInFlight.delete(decId); batchActive--; });
    irdInFlight.set(decId, p);
    return p;
});

// ── IPC: applicant read/edit ─────────────────────────────────────────────────
// IRD rejects payments when the saved applicant record is malformed (e.g. NRC
// written as "(နိုင်)" instead of "(N)") — the website lets the user fix the
// form before paying, so the app must too.
async function fetchApplicant(decId) {
    let dh = decHashCache.get(decId);
    if (!dh) {
        const rs = await fetchRegistrationStatus(decId);
        dh = rs && (rs.declarationHash || rs.DeclarationHash);
        if (!dh) return { ok: false, error: 'no declarationHash' };
    }
    const r = await bridgeFetch(`${CEIR_BASE}/openapi/API/request/applicant?declarationHash=${dh}&altcha=null`);
    if (!r.ok || (r.status || 0) >= 400) {
        return { ok: false, error: `applicant fetch failed (${r.status || r.error || '?'})` };
    }
    try { return { ok: true, dh, applicant: JSON.parse(r.text) }; }
    catch (e) { return { ok: false, error: 'bad applicant JSON' }; }
}

ipcMain.handle('get-applicant', (_e, decId) => fetchApplicant(decId));

ipcMain.handle('update-applicant', async (_e, { decId, fields }) => {
    const cur = await fetchApplicant(decId);
    if (!cur.ok) return cur;
    const merged = Object.assign({}, cur.applicant, fields);
    const token = await getAltchaToken();
    if (!token) return { ok: false, error: 'altcha failed' };
    const res = await bridgeFetch(
        `${CEIR_BASE}/openapi/API/request/applicant?declarationHash=${cur.dh}&altcha=${encodeURIComponent(token)}`,
        'POST', JSON.stringify(merged), { 'Content-Type': 'application/json' });
    if (!res.ok || (res.status || 0) >= 400) {
        return { ok: false, error: `applicant save failed (${res.status || res.error || '?'})` };
    }
    audit.recordEvent('applicant_edit', { declaration_id: decId, fields });
    log('PAY', `Applicant updated for ${decId}`);
    try { return { ok: true, applicant: JSON.parse(res.text) }; }
    catch (e) { return { ok: true, applicant: merged }; }
});

// ── IPC: Print receipt ───────────────────────────────────────────────────────
ipcMain.handle('print-receipt', async (_e, { decId, rowData, cfg }) => {
    // Try to enrich with live RegistrationStatus, fall back to row data
    let rs = await fetchRegistrationStatus(decId);
    if (!rs) {
        rs = {
            DeclarationID: decId, amount: rowData.amount || 0,
            BusinessState: rowData.pay_status || 'PENDING',
            orderCalculation: { collectingCalculations: [
                { collectingType: 'CUSTOMS_DUTY',    amount: rowData.customs    || 0, conditionPassed: true },
                { collectingType: 'COMMERCIAL_TAX',  amount: rowData.commercial || 0, conditionPassed: true },
                { collectingType: 'REDEMPTION_FINE', amount: rowData.fine       || 0, conditionPassed: true },
            ]},
            devices: [{ brand: '', model: '',
                        imeis: [rowData.imei1, rowData.imei2].filter(Boolean) }],
        };
    }

    const printerName = (cfg && cfg.brother_printer_name || '').trim();

    // Always try direct print first (auto-detects Brother QL even if name is blank).
    // Only fall back to browser preview when no QL printer is found at all.
    {
        // Extract calcs / devices for the sidecar
        const calcs = {};
        for (const c of (rs.orderCalculation && rs.orderCalculation.collectingCalculations) || []) {
            if (c.conditionPassed) calcs[c.collectingType] = c.amount;
        }
        // Match the PyQt receipt formatting exactly (s[:10] → YYYY-MM-DD)
        const confirmed = rs.confirmedDt || rs.paymentDt || '';
        const paid_on   = confirmed ? confirmed.slice(0, 10) : '';
        const status    = (rs.BusinessState || rs.businessState ||
                           rowData.pay_status || '').toUpperCase();

        const payload = {
            dec_id: decId,
            devices: (rs.devices && rs.devices.length)
                ? rs.devices.map(d => ({ brand: d.brand || '', model: d.model || '', imeis: d.imeis || [] }))
                : [{ brand: '', model: '',
                     imeis: [rowData.imei1, rowData.imei2].filter(Boolean) }],
            amount:     rs.amount || rowData.amount || 0,
            customs:    calcs.CUSTOMS_DUTY        || rowData.customs    || 0,
            commercial: calcs.COMMERCIAL_TAX      || rowData.commercial || 0,
            fine:       calcs.REDEMPTION_FINE     || rowData.fine       || 0,
            adv_income: calcs.ADVANCED_INCOME_TAX || 0,
            paid_on,
            status,
            printer_name: printerName,
            label_size:  (cfg && cfg.brother_label_size) || '62',
            qr_data: decId,
        };

        log('PRINT', `${decId}: sending to ${printerName}…`);
        const r = await receipt.printToBrotherQL(payload);
        if (r.ok) {
            log('PRINT', `${decId}: ✓ printed on ${r.printer}`);
            audit.recordEvent('print', { declaration_id: decId, ok: true, printer: r.printer });
            return { ok: true, mode: 'printer', printer: r.printer };
        }
        log('PRINT', `${decId}: ✗ printer failed (${r.error}) — falling back to browser`);
        audit.recordEvent('print', { declaration_id: decId, ok: false, error: r.error });
        // Fall through to browser fallback below
    }

    // No printer or printer failed → preview in default browser
    const html = await receipt.buildReceiptHtml(decId, rs);
    const file = await receipt.openReceiptInBrowser(decId, html);
    log('PRINT', `${decId}: opened receipt in browser (${file})`);
    return { ok: true, mode: 'browser', file };
});
