// Receipt builder + Brother QL direct print (pure JS, no Python).
const fs       = require('fs');
const os       = require('os');
const path     = require('path');
const QRCode   = require('qrcode');
const { shell } = require('electron');
const { spawn } = require('child_process');
const { renderReceiptGrayscale } = require('./receipt_image');
const brotherQl = require('./brother_ql');

function fmt(n) {
    if (!n) return '–';
    return `${Number(n).toLocaleString('en-US')} MMK`;
}

async function makeQrDataUrl(text) {
    if (!text) return '';
    try { return await QRCode.toDataURL(text, { width: 200, margin: 1 }); }
    catch (e) { return ''; }
}

/** Build HTML receipt (used for browser fallback preview). */
async function buildReceiptHtml(decId, rs) {
    const confirmed = rs.confirmedDt || rs.paymentDt || '';
    let dtStr = '–';
    if (confirmed) {
        try {
            const d = new Date(confirmed.replace('Z', '+00:00'));
            dtStr = d.toLocaleString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit' }).replace(',', '');
        } catch (e) { dtStr = confirmed.slice(0, 19); }
    }
    const calcs = {};
    for (const c of ((rs.orderCalculation && rs.orderCalculation.collectingCalculations) || [])) {
        if (c.conditionPassed) calcs[c.collectingType] = c.amount;
    }
    const total      = rs.amount || 0;
    const customs    = calcs.CUSTOMS_DUTY        || 0;
    const commercial = calcs.COMMERCIAL_TAX      || 0;
    const advInc     = calcs.ADVANCED_INCOME_TAX || 0;
    const redemption = calcs.REDEMPTION_FINE     || 0;

    let devRows = '';
    let idx = 1;
    for (const d of (rs.devices || [])) {
        const brand = d.brand || '';
        const model = d.model || '';
        for (const imei of (d.imeis || [])) {
            devRows += `<tr><td>${idx}</td><td>${brand} ${model}</td>
              <td style='word-break:break-all;font-size:6.5pt;'>${imei}</td></tr>`;
            idx++;
        }
    }
    const qr = await makeQrDataUrl(decId);
    const qrHtml = qr ? `<img src="${qr}" width="100" height="100">` : '';
    return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${decId}</title><style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:Arial,sans-serif;font-size:8pt;padding:2mm;width:58mm;}
h3{font-size:9pt;text-align:center;margin-bottom:3px;}
.aid{font-size:11pt;font-weight:bold;text-align:center;margin:2px 0 4px;}
hr{border:none;border-top:1px dashed #999;margin:3px 0;}
.sec{font-weight:bold;font-size:7.5pt;background:#efefef;padding:2px 3px;margin:4px 0 2px;}
table.t{width:100%;border-collapse:collapse;}
table.t td{padding:1px 2px;vertical-align:top;}
td.l{color:#555;width:46%;font-size:7.5pt;}
td.v{font-weight:bold;font-size:7.5pt;}
table.d{width:100%;border-collapse:collapse;font-size:7pt;}
table.d th{background:#e8e8e8;padding:2px 2px;text-align:left;}
table.d td{padding:1px 2px;border-top:1px solid #eee;}
.tot{font-size:10pt;font-weight:bold;text-align:right;margin-top:4px;border-top:1px solid #999;padding-top:3px;}
.qr{text-align:center;margin-top:5px;}
.ql{font-size:7pt;color:#444;margin-top:1px;}
@media print{ body{width:auto;padding:0;} }
</style></head><body>
<h3>CEIR Tax Receipt</h3>
<div class="aid">${decId}</div>
<hr>
<div class="sec">Registration</div>
<table class="t">
<tr><td class="l">10. App ID</td><td class="v">${decId}</td></tr>
<tr><td class="l">11. Verified</td><td class="v">${dtStr}</td></tr>
<tr><td class="l">12. Status</td><td class="v">VERIFIED</td></tr>
</table>
<div class="sec">13. Mobile Handset(s)</div>
<table class="d"><tr><th>#</th><th>Brand / Model</th><th>IMEI</th></tr>${devRows}</table>
<div class="sec">Tax Payment</div>
<table class="t">
<tr><td class="l">14. Paid on</td><td class="v">${dtStr}</td></tr>
<tr><td class="l">15. Customs Duty</td><td class="v">${fmt(customs)}</td></tr>
<tr><td class="l">16. Commercial Tax</td><td class="v">${fmt(commercial)}</td></tr>
${advInc ? `<tr><td class="l">17. Adv. Income Tax</td><td class="v">${fmt(advInc)}</td></tr>` : ''}
<tr><td class="l">18. Redemption Fine</td><td class="v">${fmt(redemption)}</td></tr>
</table>
<div class="tot">Total: ${fmt(total)}</div>
${qrHtml ? `<hr><div class="qr">${qrHtml}<div class="ql">${decId}</div></div>` : ''}
</body></html>`;
}

async function openReceiptInBrowser(decId, html) {
    const file = path.join(os.tmpdir(), `ceir_receipt_${decId}_${Date.now()}.html`);
    fs.writeFileSync(file, html, 'utf8');
    await shell.openPath(file);
    return file;
}

// ── CUPS helpers ────────────────────────────────────────────────────────────
function listCupsPrinters() {
    return new Promise((resolve) => {
        const p = spawn('lpstat', ['-a']);
        let out = '';
        p.stdout.on('data', d => out += d.toString());
        p.on('close', () => {
            const list = out.split('\n').map(l => (l.split(' ')[0] || '').trim()).filter(Boolean);
            resolve(list);
        });
        p.on('error', () => resolve([]));
    });
}

async function resolvePrinterName(name) {
    const list = await listCupsPrinters();
    // Try exact + normalised match if a name was provided
    if (name) {
        if (list.includes(name)) return name;
        const norm = name.toLowerCase().replace(/[-\s]/g, '_');
        for (const p of list) if (p.toLowerCase().replace(/[-]/g, '_') === norm) return p;
    }
    // Fall back to auto-detect: any Brother QL in CUPS
    for (const p of list) {
        const lc = p.toLowerCase();
        if (lc.includes('ql') && (lc.includes('820') || lc.includes('brother'))) return p;
    }
    for (const p of list) {
        if (p.toLowerCase().includes('brother')) return p;
    }
    return null;
}

// ── Brother QL direct print ─────────────────────────────────────────────────
/**
 * Print receipt to Brother QL printer via lpr -oraw.
 * payload = { dec_id, devices, amount, customs, commercial, fine, adv_income,
 *             paid_on, printer_name, label_size, qr_data }
 */
async function printToBrotherQL(payload) {
    try {
        // 1) Build receipt as grayscale image (696 wide)
        const { gray, width, height } = await renderReceiptGrayscale(payload);
        if (width !== brotherQl.DOTS_PRINTABLE) {
            return { ok: false, error: `image width ${width}, expected ${brotherQl.DOTS_PRINTABLE}` };
        }

        // 2) Convert to 1-bit packed raster (90 bytes × height rows)
        const { bits1 } = brotherQl.grayscaleToBrotherRaster(gray, width, height, 178);

        // 3) Wrap in Brother QL-820NWB protocol bytes
        const raw = brotherQl.buildRaster({ bits1, height });

        // 4) Resolve printer in CUPS
        const resolved = await resolvePrinterName((payload.printer_name || '').trim());
        if (!resolved) {
            const list = await listCupsPrinters();
            return { ok: false, error: `printer not found in CUPS. Available: ${list.join(', ') || '(none)'}` };
        }

        // 5) Write to temp file, send via lpr -oraw
        const file = path.join(os.tmpdir(), `ceir_raster_${Date.now()}.bin`);
        fs.writeFileSync(file, raw);
        return await new Promise((resolve) => {
            const p = spawn('lpr', ['-P', resolved, '-oraw', file]);
            let err = '';
            p.stderr.on('data', d => err += d.toString());
            p.on('close', (code) => {
                try { fs.unlinkSync(file); } catch (e) {}
                if (code === 0) resolve({ ok: true, printer: resolved });
                else resolve({ ok: false, error: err.trim() || `lpr exit ${code}` });
            });
            p.on('error', e => resolve({ ok: false, error: e.message }));
        });
    } catch (e) {
        return { ok: false, error: e.message };
    }
}

module.exports = { buildReceiptHtml, openReceiptInBrowser, printToBrotherQL, listCupsPrinters };
