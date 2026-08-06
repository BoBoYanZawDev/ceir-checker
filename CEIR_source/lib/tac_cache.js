// Persistent TAC → {brand, model} cache. TAC is the first 8 digits of an
// IMEI and uniquely identifies a phone model — we only need to look it up
// once per TAC, ever. Stored in userData/tac-cache.json.
const fs   = require('fs');
const path = require('path');
const { app } = require('electron');

function file() {
    return path.join(app.getPath('userData'), 'tac-cache.json');
}

function load() {
    try { return JSON.parse(fs.readFileSync(file(), 'utf8')); }
    catch (e) { return {}; }
}
function save(data) {
    try {
        fs.mkdirSync(path.dirname(file()), { recursive: true });
        fs.writeFileSync(file(), JSON.stringify(data));
    } catch (e) { /* ignore */ }
}

let cache = null;
function get(tac) {
    if (cache === null) cache = load();
    const v = cache[tac];
    // Treat blank entries (saved from a broken probe earlier) as cache miss.
    if (!v) return null;
    if (!v.brand && !v.model) return null;
    return v;
}
function set(tac, info) {
    if (cache === null) cache = load();
    cache[tac] = info;
    save(cache);
}
function clear() {
    cache = {};
    save(cache);
}

module.exports = { get, set, clear };
