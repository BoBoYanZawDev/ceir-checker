// Persistent in-memory state for the Tax Register table.
// Saved to userData/state.json on every write. Survives crashes, force-quits,
// and reboots. Restored automatically on app launch.
const fs   = require('fs');
const path = require('path');
const { app } = require('electron');

function file() {
    return path.join(app.getPath('userData'), 'state.json');
}

function load() {
    try {
        const raw = fs.readFileSync(file(), 'utf8');
        const parsed = JSON.parse(raw);
        return {
            taxResults: Array.isArray(parsed.taxResults) ? parsed.taxResults : [],
            activeSession: typeof parsed.activeSession === 'string' ? parsed.activeSession : '',
            workflowPhase: parsed.workflowPhase || 'idle',
            updatedAt: parsed.updatedAt || null,
        };
    } catch (e) {
        return { taxResults: [], activeSession: '', workflowPhase: 'idle', updatedAt: null };
    }
}

// Debounced write — collapse rapid changes (batch operations write often)
let pendingWrite = null;
let pendingState = null;
function save(state) {
    pendingState = { ...state, updatedAt: new Date().toISOString() };
    if (pendingWrite) return;
    pendingWrite = setTimeout(() => {
        try {
            fs.mkdirSync(path.dirname(file()), { recursive: true });
            fs.writeFileSync(file(), JSON.stringify(pendingState));
        } catch (e) {
            console.error('[state] write failed:', e.message);
        }
        pendingWrite = null;
        pendingState = null;
    }, 300);
}

function clear() {
    try { fs.unlinkSync(file()); } catch (e) {}
}

module.exports = { load, save, clear };
