// Cloud account + activity-log mirror (Supabase — same project as ceir-ops).
//
// Login-only, like ceir-mobile: accounts are created by staff, employees just
// sign in. The session is persisted to userData so the app works offline once
// logged in. Every audit event (lib/audit.js) is ALSO queued here and uploaded
// to app_activity_logs tagged with the login's user_id; the queue survives
// restarts and network outages, and rows are deduped server-side by client_id,
// so nothing is lost and nothing is double-counted.
//
// The URL + publishable key are public by design (same values as ceir-mobile);
// everything sensitive is protected server-side by RLS.
const fs     = require('fs');
const os     = require('os');
const path   = require('path');
const crypto = require('crypto');
const { createClient } = require('@supabase/supabase-js');

const SUPABASE_URL      = 'https://jruyhemtwpfbukgnnrgl.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_Eso7qBPz0jXkJLk78M6Eqg_MoFcBNX7';

const FLUSH_INTERVAL_MS = 20_000;
const FLUSH_BATCH       = 500;
const QUEUE_MAX         = 20_000;   // safety cap; oldest rows drop beyond this
const FIELD_MAX_CHARS   = 4_000;    // truncate huge request/response bodies

let client   = null;
let profile  = null;               // { user_id, email, display_name, active }
let currentUid = null;             // uid of the signed-in user, tracked live —
                                   // stamped on every queued row so work done
                                   // by A can never upload under B's account
                                   // on a shared computer
let queue    = [];
let queueFile   = null;
let sessionFile = null;
let saveTimer   = null;
let flushTimer  = null;
let flushing    = false;

// ── session storage (plain JSON file in userData) ──────────────────────────
function fileStorage(file) {
    const read = () => { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; } };
    return {
        getItem:    (k)    => read()[k] ?? null,
        setItem:    (k, v) => { const j = read(); j[k] = v; fs.writeFileSync(file, JSON.stringify(j)); },
        removeItem: (k)    => { const j = read(); delete j[k]; fs.writeFileSync(file, JSON.stringify(j)); },
    };
}

let appVersion = '';

function init(app) {
    try { appVersion = app.getVersion(); } catch {}
    const dir   = app.getPath('userData');
    sessionFile = path.join(dir, 'cloud-session.json');
    queueFile   = path.join(dir, 'cloud-queue.json');
    try { queue = JSON.parse(fs.readFileSync(queueFile, 'utf8')); } catch { queue = []; }
    if (!Array.isArray(queue)) queue = [];

    // Realtime is unused, but supabase-js still probes for a native WebSocket
    // (absent in Electron's Node 20) — a stub transport skips that probe.
    class NoopWebSocket {
        constructor() { this.readyState = 3; /* CLOSED */ }
        close() {} send() {}
        addEventListener() {} removeEventListener() {}
        set onopen(_) {} set onclose(_) {} set onerror(_) {} set onmessage(_) {}
    }
    try {
        client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
            auth: {
                storage: fileStorage(sessionFile),
                persistSession: true,
                autoRefreshToken: true,
                detectSessionInUrl: false,
            },
            realtime: { transport: NoopWebSocket },
        });
    } catch (e) {
        console.error('[cloud] client init failed:', e.message);
        client = null;   // app still runs; events keep queueing locally
    }

    if (client) {
        client.auth.onAuthStateChange((_event, session) => {
            currentUid = session?.user?.id ?? null;
        });
    }

    flushTimer = setInterval(() => { flush().catch(() => {}); }, FLUSH_INTERVAL_MS);
    if (flushTimer.unref) flushTimer.unref();
}

// ── auth ────────────────────────────────────────────────────────────────────
async function getSession() {
    try { return (await client.auth.getSession()).data.session || null; }
    catch { return null; }
}

// Accounts come in two kinds sharing one login screen:
//   employee — employee_users (internal staff, no credits)
//   customer — app_profiles  (same account as the ceir-mobile app; prepaid
//              credits, registration consumes credit_per_phone per phone)
async function loadProfile() {
    const session = await getSession();
    if (!session) { profile = null; return null; }
    try {
        const { data: emp } = await client
            .from('employee_users')
            .select('display_name, active, employee_id')
            .eq('user_id', session.user.id)
            .maybeSingle();
        if (emp) {
            profile = {
                kind: 'employee',
                user_id: session.user.id,
                email: session.user.email,
                display_name: emp.display_name || session.user.email,
                active: !!emp.active,
                registered: true,
            };
        } else {
            const { data: cust } = await client
                .from('app_profiles')
                .select('shop_name, active')
                .eq('user_id', session.user.id)
                .maybeSingle();
            profile = {
                kind: cust ? 'customer' : 'none',
                user_id: session.user.id,
                email: session.user.email,
                display_name: (cust && cust.shop_name) || session.user.email,
                active: cust ? !!cust.active : false,
                registered: !!cust,
            };
        }
        saveProfileCache(profile);
    } catch {
        // Offline: last successfully-loaded profile keeps the app usable
        // (kind matters — a customer must stay credit-gated offline too).
        profile = loadProfileCache(session.user.id) || {
            kind: 'employee', user_id: session.user.id, email: session.user.email,
            display_name: session.user.email, active: true, registered: true,
        };
    }
    return profile;
}

function profileCacheFile() { return sessionFile.replace('cloud-session.json', 'cloud-profile.json'); }
function saveProfileCache(p) { try { fs.writeFileSync(profileCacheFile(), JSON.stringify(p)); } catch {} }
function loadProfileCache(uid) {
    try {
        const p = JSON.parse(fs.readFileSync(profileCacheFile(), 'utf8'));
        return p && p.user_id === uid ? p : null;
    } catch { return null; }
}

async function signIn(email, password) {
    try {
        const { error } = await client.auth.signInWithPassword({ email: String(email || '').trim(), password });
        if (error) return { ok: false, message: error.message };
        const p = await loadProfile();
        if (p && !p.registered) {
            await client.auth.signOut();
            profile = null;
            return { ok: false, message: 'This account is not registered (neither employee nor app customer). Ask the admin.' };
        }
        if (p && !p.active) {
            await client.auth.signOut();
            profile = null;
            return { ok: false, message: `This ${p.kind} account is disabled. Ask the admin.` };
        }
        flush().catch(() => {});
        return { ok: true, profile: p };
    } catch (e) {
        return { ok: false, message: 'Network error — internet is required for the first login. (' + e.message + ')' };
    }
}

// ── prepaid credits (customer accounts; same RPCs as ceir-mobile) ───────────
async function creditInfo() {
    try {
        const [bal, cost] = await Promise.all([
            client.rpc('app_balance'),
            client.rpc('app_credit_cost'),
        ]);
        if (bal.error) throw bal.error;
        return { ok: true, balance: Number(bal.data ?? 0), cost: Math.max(1, Number(cost.data ?? 2)) };
    } catch (e) {
        return { ok: false, error: e.message || 'network' };
    }
}

// Spend credit_per_phone for one registered phone, idempotent per ref
// (Declaration ID) — retries and re-runs never double-charge.
async function consumeCredit(ref, note) {
    try {
        const { data, error } = await client.rpc('consume_credit', { p_ref: ref, p_note: note ?? null });
        if (error) {
            const msg = error.message || '';
            if (/insufficient_credits/.test(msg)) return { ok: false, reason: 'insufficient', error: 'Out of credits — top up to continue.' };
            if (/no_active_account/.test(msg))    return { ok: false, reason: 'no_account', error: 'Account inactive — contact your provider.' };
            if (/not_authenticated/.test(msg))    return { ok: false, reason: 'auth', error: 'Session expired — restart the app and sign in.' };
            return { ok: false, reason: 'network', error: msg || 'Network error' };
        }
        return { ok: true, balance: Number(data ?? 0) };
    } catch (e) {
        return { ok: false, reason: 'network', error: e.message };
    }
}

async function signOut() {
    try { await flush(); } catch {}
    try { await client.auth.signOut(); } catch {}
    profile = null;
}

function getProfile() { return profile; }

// ── activity-log queue ──────────────────────────────────────────────────────
function truncate(v) {
    if (typeof v === 'string' && v.length > FIELD_MAX_CHARS) return v.slice(0, FIELD_MAX_CHARS) + '…[truncated]';
    return v;
}
const toInt = (v) => { const n = Number(v); return Number.isFinite(n) ? Math.round(n) : null; };
const toStr = (v) => (v === null || v === undefined || v === '' ? null : String(v));

/** Queue one audit event for upload. Never throws. `evt` is the full JSONL object. */
function logEvent(evt) {
    try {
        const payload = {};
        for (const [k, v] of Object.entries(evt)) payload[k] = truncate(v);
        if (appVersion) payload.app_version = appVersion;
        queue.push({
            client_id:      crypto.randomUUID(),
            user_id:        currentUid,        // null before login → machine event
            ts:             evt.timestamp || new Date().toISOString(),
            event:          String(evt.event || 'event'),
            declaration_id: toStr(evt.declaration_id),
            imei1:          toStr(evt.imei1),
            imei2:          toStr(evt.imei2),
            old_status:     toStr(evt.old_status),
            new_status:     toStr(evt.new_status),
            source:         toStr(evt.source),
            amount:         toInt(evt.amount),
            customs:        toInt(evt.customs),
            commercial:     toInt(evt.commercial),
            fine:           toInt(evt.fine),
            // http_error events put the numeric HTTP code in `status`;
            // tax_register uses `status` for OK/FAILED text + `http_status`.
            status:         evt.event === 'http_error' ? null : toStr(evt.status),
            http_status:    toInt(evt.http_status ?? (evt.event === 'http_error' ? evt.status : null)),
            error:          toStr(truncate(evt.error)),
            device:         os.hostname(),
            payload,
        });
        if (queue.length > QUEUE_MAX) queue.splice(0, queue.length - QUEUE_MAX);
        saveQueueSoon();
    } catch (e) {
        console.error('[cloud] enqueue failed:', e.message);
    }
}

function saveQueueSoon() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => {
        saveTimer = null;
        try { fs.writeFileSync(queueFile, JSON.stringify(queue)); } catch {}
    }, 2000);
    if (saveTimer.unref) saveTimer.unref();
}

async function flush() {
    if (flushing || !queue.length || !client) return;
    flushing = true;
    try {
        const session = await getSession();
        if (!session) return;
        const uid = session.user.id;
        // Rows from ANOTHER user's session must wait for that user to sign in
        // again (RLS rejects them under this session anyway). Drop them after
        // 30 days so the queue can't grow forever on a shared machine.
        const cutoff = Date.now() - 30 * 86400_000;
        for (let i = queue.length - 1; i >= 0; i--) {
            const r = queue[i];
            if (r.user_id && r.user_id !== uid && new Date(r.ts).getTime() < cutoff) queue.splice(i, 1);
        }
        while (true) {
            const batch = [];
            const idx = [];
            for (let i = 0; i < queue.length && batch.length < FLUSH_BATCH; i++) {
                const r = queue[i];
                if (!r.user_id || r.user_id === uid) { batch.push({ ...r, user_id: uid }); idx.push(i); }
            }
            if (!batch.length) break;
            const { error } = await client
                .from('app_activity_logs')
                .upsert(batch, { onConflict: 'user_id,client_id', ignoreDuplicates: true });
            if (error) { console.error('[cloud] flush failed:', error.message); break; }
            for (let k = idx.length - 1; k >= 0; k--) queue.splice(idx[k], 1);
            saveQueueSoon();
        }
    } catch (e) {
        console.error('[cloud] flush error:', e.message);   // offline — retry on next tick
    } finally {
        flushing = false;
    }
}

function queueLength() { return queue.length; }

module.exports = {
    init, getSession, signIn, signOut, loadProfile, getProfile,
    creditInfo, consumeCredit,
    logEvent, flush, queueLength,
};
