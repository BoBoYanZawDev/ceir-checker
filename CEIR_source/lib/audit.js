// Persistent audit log — writes JSONL + CSV per day to userData/logs/.
// Every Tax Register attempt is captured with full request/response so the
// Declaration ID is never lost even if the app crashes.
const fs   = require('fs');
const path = require('path');
const { app, shell } = require('electron');
const cloud = require('./cloud');   // mirrors every event to Supabase (offline-safe queue)

function logsDir() {
    const dir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(dir, { recursive: true });
    return dir;
}

function ymd(d = new Date()) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function jsonlPath(date)  { return path.join(logsDir(), `audit_${ymd(date)}.jsonl`); }
function csvPath(date)    { return path.join(logsDir(), `tax_log_${ymd(date)}.csv`); }
function payCsvPath(date) { return path.join(logsDir(), `pay_log_${ymd(date)}.csv`); }

// ── Headers (created once) ─────────────────────────────────────────────────
function ensureCsvHeader(filepath, header) {
    if (!fs.existsSync(filepath) || fs.statSync(filepath).size === 0) {
        fs.writeFileSync(filepath, header + '\n');
    }
}

function csvEscape(v) {
    if (v === null || v === undefined) return '';
    const s = String(v);
    if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
}

// ── Public API ─────────────────────────────────────────────────────────────

/**
 * Record a Tax Register attempt — captures everything needed to recover an
 * AppID even if the app crashes immediately after.
 *
 * entry: {
 *   imei1, imei2,
 *   request_body (the JSON sent),
 *   http_status, response_text (raw),
 *   declaration_id, amount, customs, commercial, fine,
 *   status: "OK" | "FAILED" | "ERROR: ..."
 *   error: optional string
 * }
 */
function recordTaxRegister(entry) {
    const ts = new Date();
    const full = {
        timestamp: ts.toISOString(),
        event: 'tax_register',
        ...entry,
    };
    try { cloud.logEvent(full); } catch {}
    try {
        // JSONL (machine readable, full detail)
        fs.appendFileSync(jsonlPath(ts), JSON.stringify(full) + '\n');

        // CSV mirror (spreadsheet friendly)
        ensureCsvHeader(csvPath(ts),
            'timestamp,imei1,imei2,declaration_id,amount,customs,commercial,fine,status,http_status,error');
        const csv = [
            ts.toISOString(),
            entry.imei1, entry.imei2 || '',
            entry.declaration_id || '',
            entry.amount || '',
            entry.customs || '',
            entry.commercial || '',
            entry.fine || '',
            entry.status || '',
            entry.http_status || '',
            entry.error || '',
        ].map(csvEscape).join(',');
        fs.appendFileSync(csvPath(ts), csv + '\n');
    } catch (e) {
        // Logging itself failed — fall back to stderr; never throw
        console.error('[audit] write failed:', e.message);
    }
}

/** Record a payment-related event (status check, mark paid, etc.) */
function recordPayment(entry) {
    const ts = new Date();
    const full = {
        timestamp: ts.toISOString(),
        event: 'payment',
        ...entry,
    };
    try { cloud.logEvent(full); } catch {}
    try {
        fs.appendFileSync(jsonlPath(ts), JSON.stringify(full) + '\n');
        ensureCsvHeader(payCsvPath(ts),
            'timestamp,declaration_id,old_status,new_status,source,error');
        const csv = [
            ts.toISOString(),
            entry.declaration_id || '',
            entry.old_status || '',
            entry.new_status || '',
            entry.source || '',
            entry.error || '',
        ].map(csvEscape).join(',');
        fs.appendFileSync(payCsvPath(ts), csv + '\n');
    } catch (e) {
        console.error('[audit] write failed:', e.message);
    }
}

/** Generic event (for connect/disconnect, errors, etc.) */
function recordEvent(event, payload = {}) {
    const ts = new Date();
    const full = { timestamp: ts.toISOString(), event, ...payload };
    try { cloud.logEvent(full); } catch {}
    try {
        fs.appendFileSync(jsonlPath(ts), JSON.stringify(full) + '\n');
    } catch (e) { console.error('[audit] write failed:', e.message); }
}

function getLogsDir() { return logsDir(); }
function openLogsFolder() { shell.openPath(logsDir()); }

/**
 * Read JSONL events for a given date. Returns an array of objects, or [] if
 * file missing. Use for "resume incomplete registrations" + stats.
 */
function readEvents(date = new Date()) {
    const f = jsonlPath(date);
    if (!fs.existsSync(f)) return [];
    try {
        return fs.readFileSync(f, 'utf8').split('\n')
            .filter(Boolean).map(line => { try { return JSON.parse(line); } catch (e) { return null; } })
            .filter(Boolean);
    } catch (e) { return []; }
}

/** Returns daily counts of tax_register events for the last `days` days. */
function dailyStats(days = 7) {
    const out = [];
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(); d.setDate(d.getDate() - i);
        const evs = readEvents(d);
        let registered = 0, paid = 0, failed = 0;
        const paidDecls = new Set();
        for (const e of evs) {
            if (e.event === 'tax_register') {
                if (e.declaration_id) registered++;
                if (e.status && !e.status.startsWith('OK') && e.status !== 'OK') failed++;
            }
            if (e.event === 'payment' && e.new_status === 'PAID') {
                paidDecls.add(e.declaration_id);
            }
        }
        out.push({ date: ymd(d), registered, paid: paidDecls.size, failed });
    }
    return out;
}

module.exports = {
    recordTaxRegister, recordPayment, recordEvent,
    getLogsDir, openLogsFolder,
    readEvents, dailyStats,
};
