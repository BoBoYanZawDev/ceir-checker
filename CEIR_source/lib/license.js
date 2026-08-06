// Offline license verification — same scheme as ceir-imei-check.
//
// Activation codes are ed25519-signed payloads of the form:
//   version(1) | machine_id(15) | expires_at_unix(4)  = 20 bytes
//   + signature(64 bytes) = 84 bytes total
//   → 135-char base32 string prefixed with "KEY-" and dashes every 5 chars.
//
// The public key lives in ../keys/public.pem — the SAME keypair as
// ceir-imei-check-admin, so the admin generates keys with the same
// `node generate.js --mid ...` tool. But the machine-ID salt below is
// different ("ceir-tool-v1:" vs "ceir-imei-v1:"), so this app shows a
// DIFFERENT Machine ID on the same computer: a key issued for the IMEI
// Checker can never activate the CEIR Tool, and vice versa.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { machineIdSync } = require('node-machine-id');

const PUB_PEM_PATH = path.join(__dirname, '..', 'keys', 'public.pem');
let PUBLIC_KEY = null;
function loadPublicKey() {
    if (PUBLIC_KEY) return PUBLIC_KEY;
    const pem = fs.readFileSync(PUB_PEM_PATH, 'utf8');
    if (!pem.includes('BEGIN PUBLIC KEY')) {
        throw new Error('public.pem is not a real PEM — copy it from ceir-imei-check-admin/keys/');
    }
    PUBLIC_KEY = crypto.createPublicKey(pem);
    return PUBLIC_KEY;
}

// ── base32 (RFC 4648) ───────────────────────────────────────────────────
const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
function b32Encode(buf) {
    let bits = '';
    for (const b of buf) bits += b.toString(2).padStart(8, '0');
    let out = '';
    for (let i = 0; i < bits.length; i += 5) {
        const chunk = bits.slice(i, i + 5).padEnd(5, '0');
        out += B32[parseInt(chunk, 2)];
    }
    return out;
}
function b32Decode(s) {
    const bits = [];
    for (const c of s) {
        const idx = B32.indexOf(c);
        if (idx < 0) throw new Error('Invalid base32 char: ' + c);
        for (let i = 4; i >= 0; i--) bits.push((idx >> i) & 1);
    }
    const bytes = Buffer.alloc(Math.floor(bits.length / 8));
    for (let i = 0; i < bytes.length; i++) {
        let b = 0;
        for (let j = 0; j < 8; j++) b = (b << 1) | bits[i * 8 + j];
        bytes[i] = b;
    }
    return bytes;
}

// ── Machine ID (hashed, deterministic per machine) ──────────────────────
function getMachineIdBytes() {
    // node-machine-id reads macOS IOPlatformUUID / Windows MachineGuid /
    // Linux /etc/machine-id. Deterministic across reboots.
    const raw = machineIdSync({ original: false });
    // App-specific salt: keys for this app cannot activate ceir-imei-check.
    const digest = crypto.createHash('sha256').update('ceir-tool-v1:' + raw).digest();
    return digest.subarray(0, 15); // 120 bits
}

function getMachineIdFormatted() {
    const b32 = b32Encode(getMachineIdBytes());
    const groups = b32.match(/.{1,4}/g);
    return 'MID-' + groups.join('-');
}

// ── Verify an activation code ───────────────────────────────────────────
function verifyLicenseCode(rawCode) {
    // Strip everything except base32 alphabet
    const clean = String(rawCode || '')
        .toUpperCase()
        .replace(/^KEY-?/, '')
        .replace(/[^A-Z2-7]/g, '');

    let bytes;
    try { bytes = b32Decode(clean); }
    catch (e) { return { ok: false, reason: 'malformed' }; }

    if (bytes.length < 84) return { ok: false, reason: 'too_short' };
    const payload = bytes.subarray(0, 20);
    const sig     = bytes.subarray(20, 84);

    if (payload[0] !== 1) return { ok: false, reason: 'unsupported_version' };

    const keyedMid = payload.subarray(1, 16);
    const exp = payload.readUInt32BE(16);

    // Signature check (protects against tampering with mid/exp)
    let sigOk = false;
    try { sigOk = crypto.verify(null, payload, loadPublicKey(), sig); }
    catch { sigOk = false; }
    if (!sigOk) return { ok: false, reason: 'invalid_signature' };

    // Machine binding
    const localMid = getMachineIdBytes();
    if (!keyedMid.equals(localMid)) return { ok: false, reason: 'wrong_machine' };

    // Expiry
    const now = Math.floor(Date.now() / 1000);
    if (now >= exp) return { ok: false, reason: 'expired', expiresAt: exp };

    return { ok: true, expiresAt: exp };
}

// ── License storage (in Electron userData) ──────────────────────────────
function licenseFilePath(app) {
    return path.join(app.getPath('userData'), 'license.dat');
}
function readStoredLicense(app) {
    try {
        const p = licenseFilePath(app);
        if (!fs.existsSync(p)) return null;
        return fs.readFileSync(p, 'utf8').trim();
    } catch { return null; }
}
function writeStoredLicense(app, code) {
    const p = licenseFilePath(app);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, code, 'utf8');
}
function clearStoredLicense(app) {
    try { fs.unlinkSync(licenseFilePath(app)); } catch {}
}

function checkStoredLicense(app) {
    const code = readStoredLicense(app);
    if (!code) return { ok: false, reason: 'not_activated' };
    const res = verifyLicenseCode(code);
    return { ...res, code };
}

module.exports = {
    getMachineIdFormatted,
    getMachineIdBytes,
    verifyLicenseCode,
    checkStoredLicense,
    readStoredLicense,
    writeStoredLicense,
    clearStoredLicense,
};
