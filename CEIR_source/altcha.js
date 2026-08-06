// Altcha proof-of-work solver — Node.js port of the Python implementation
// in cf_solver / ceir_batch. SHA256(salt + number) == challenge.
const crypto = require('crypto');

function sha256Hex(s) {
    return crypto.createHash('sha256').update(s).digest('hex');
}

/**
 * Brute-force the PoW: find number where SHA256(salt + number) == challenge.
 * Returns base64-encoded token, or null on failure.
 */
async function solve(challenge) {
    const target = challenge.challenge;
    const salt   = challenge.salt;
    const max    = challenge.maxnumber || 1_000_000;
    const t0     = Date.now();

    for (let n = 0; n < max; n++) {
        const hash = sha256Hex(salt + n);
        if (hash === target) {
            const took = Date.now() - t0;
            const payload = {
                algorithm: challenge.algorithm,
                challenge: challenge.challenge,
                number: n,
                salt: challenge.salt,
                signature: challenge.signature,
                took,
            };
            return Buffer.from(JSON.stringify(payload)).toString('base64');
        }
        // Yield to event loop every 50k iterations so UI stays responsive
        if (n % 50000 === 0) {
            await new Promise(r => setImmediate(r));
        }
    }
    return null;
}

module.exports = { solve };
