// Builds a 696px-wide receipt image for Brother QL-820NWB.
// Renders an SVG to grayscale via `sharp` (prebuilt binaries — no compile).
// Layout closely matches the PyQt tool's `_build_receipt_image()` output.
const sharp  = require('sharp');
const QRCode = require('qrcode');

const W       = 696;
const PAD     = 20;
const LINE    = 28;        // matches PyQt
const SMALL   = 22;        // matches PyQt label/value font size
const FONT    = 'Helvetica, Arial, sans-serif';

function escapeXml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}
function fmtMoney(n) {
    if (!n) return '—';
    return `${Number(n).toLocaleString('en-US')} MMK`;
}
function dash(s) { return (s == null || s === '') ? '—' : s; }

/**
 * @param {object} d  Receipt data, see main.js print-receipt handler:
 *   d.dec_id, d.amount, d.customs, d.commercial, d.fine, d.adv_income,
 *   d.paid_on, d.status, d.devices: [{brand,model,imeis:[]}], d.qr_data
 * @returns {Promise<{gray:Buffer, width:number, height:number}>}
 */
async function renderReceiptGrayscale(d) {
    // Pre-render QR
    let qrB64 = '';
    if (d.qr_data) {
        try {
            const buf = await QRCode.toBuffer(d.qr_data, { width: 200, margin: 2 });
            qrB64 = buf.toString('base64');
        } catch (e) {}
    }

    // ── Build SVG ────────────────────────────────────────────────────────
    // x positions for label/value layout (matches PyQt: label at PAD+4, value at W/2)
    const X_LABEL = PAD + 4;
    const X_VALUE = Math.floor(W / 2);
    // Device-table columns: IMEI sits at X_VALUE so it lines up with every
    // other value column above (App ID / Verified / Status / Paid on / …).
    const COL_NUM   = PAD + 4;
    const COL_MODEL = COL_NUM + 40;
    const COL_IMEI  = X_VALUE;

    const parts = [];
    let y = PAD;

    // helper: dashed / solid horizontal rule (colors match PyQt: dashed #999, solid #333)
    const rule = (yy, dashed = false) => {
        if (dashed) {
            parts.push(`<line x1="${PAD}" y1="${yy}" x2="${W - PAD}" y2="${yy}" ` +
                       `stroke="#999" stroke-dasharray="4 4" stroke-width="1"/>`);
        } else {
            parts.push(`<line x1="${PAD}" y1="${yy}" x2="${W - PAD}" y2="${yy}" ` +
                       `stroke="#333" stroke-width="2"/>`);
        }
        return yy + 6;
    };

    // helper: section header — just bold black text (the grey bar that PyQt
    // draws is invisible on thermal anyway after the threshold, so we drop it).
    const sectionHdr = (yy, text) => {
        parts.push(`<text x="${PAD + 4}" y="${yy + 22}" font-family="${FONT}" font-weight="bold" ` +
                   `font-size="22" fill="black">${escapeXml(text)}</text>`);
        return yy + LINE + 8;
    };

    // helper: label/value row. Label uses BLACK (not grey) so it survives the
    // brother_ql 178 threshold — anything lighter than ~#3c3c3c gets dropped.
    const kvRow = (yy, label, value) => {
        parts.push(`<text x="${X_LABEL}" y="${yy + 22}" font-family="${FONT}" ` +
                   `font-size="${SMALL}" fill="black">${escapeXml(label)}</text>`);
        parts.push(`<text x="${X_VALUE}" y="${yy + 22}" font-family="${FONT}" font-weight="bold" ` +
                   `font-size="${SMALL}" fill="black">${escapeXml(value)}</text>`);
        return yy + LINE;
    };

    // Dedupe "Samsung" / "Samsung Galaxy A06" → "Samsung Galaxy A06".
    // If the model already starts with the brand (case-insensitive), drop the
    // brand prefix. Otherwise join them with a space.
    const joinBrandModel = (brand, model) => {
        const b = (brand || '').toString().trim();
        const m = (model || '').toString().trim();
        if (!b) return m || '—';
        if (!m) return b;
        if (m.toLowerCase().startsWith(b.toLowerCase())) return m;
        return `${b} ${m}`.replace(/\s+/g, ' ').trim();
    };

    // ── Title ────────────────────────────────────────────────────────────
    parts.push(`<text x="${W / 2}" y="${y + 24}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="30" text-anchor="middle" fill="black">CEIR Tax Receipt</text>`);
    y += LINE + 8;

    // ── Big Declaration ID ───────────────────────────────────────────────
    parts.push(`<text x="${W / 2}" y="${y + 22}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="26" text-anchor="middle" fill="black">${escapeXml(d.dec_id || '')}</text>`);
    y += LINE + PAD;

    y = rule(y, true) + 4;

    // ── Registration section ─────────────────────────────────────────────
    y = sectionHdr(y, 'Registration');
    y = kvRow(y, '10. App ID',  d.dec_id || '');
    y = kvRow(y, '11. Verified', dash(d.paid_on));
    y = kvRow(y, '12. Status',   dash(d.status));
    y += 6;

    // ── Devices section ──────────────────────────────────────────────────
    y = sectionHdr(y, '13. Mobile Handset(s)');
    // Column headers (PyQt fnt_hdr: size 22 BOLD black)
    parts.push(`<text x="${COL_NUM}"   y="${y + 22}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="22" fill="black">#</text>`);
    parts.push(`<text x="${COL_MODEL}" y="${y + 22}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="22" fill="black">Brand / Model</text>`);
    parts.push(`<text x="${COL_IMEI}"  y="${y + 22}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="22" fill="black">IMEI</text>`);
    y += LINE;
    let idx = 1;
    const devices = (d.devices && d.devices.length)
        ? d.devices : [{ brand: '', model: '', imeis: [] }];
    for (const dev of devices) {
        const brandModel = joinBrandModel(dev.brand, dev.model);
        for (const imei of (dev.imeis || [])) {
            // Device rows: PyQt fnt_label (22, NOT bold, black) for every column
            parts.push(`<text x="${COL_NUM}"   y="${y + 22}" font-family="${FONT}" ` +
                       `font-size="${SMALL}" fill="black">${idx}</text>`);
            parts.push(`<text x="${COL_MODEL}" y="${y + 22}" font-family="${FONT}" ` +
                       `font-size="${SMALL}" fill="black">${escapeXml(brandModel)}</text>`);
            parts.push(`<text x="${COL_IMEI}"  y="${y + 22}" font-family="${FONT}" ` +
                       `font-size="${SMALL}" fill="black">${escapeXml(String(imei))}</text>`);
            y += LINE;
            idx++;
        }
    }
    y += 6;

    // ── Tax Payment section ──────────────────────────────────────────────
    y = sectionHdr(y, 'Tax Payment');
    y = kvRow(y, '14. Paid on',         dash(d.paid_on));
    y = kvRow(y, '15. Customs Duty',    fmtMoney(d.customs));
    y = kvRow(y, '16. Commercial Tax',  fmtMoney(d.commercial));
    y = kvRow(y, '17. Adv. Income Tax', fmtMoney(d.adv_income));
    y = kvRow(y, '18. Redemption Fine', fmtMoney(d.fine));
    y += 6;

    // ── Total ────────────────────────────────────────────────────────────
    y = rule(y, true) + 4;
    parts.push(`<text x="${W - PAD}" y="${y + 26}" font-family="${FONT}" font-weight="bold" ` +
               `font-size="30" text-anchor="end" fill="black">` +
               `Total: ${escapeXml(fmtMoney(d.amount))}</text>`);
    y += LINE + 8;
    y = rule(y, true) + PAD;

    // ── QR ───────────────────────────────────────────────────────────────
    if (qrB64) {
        const qrSize = 200;
        parts.push(`<image x="${(W - qrSize) / 2}" y="${y}" width="${qrSize}" height="${qrSize}" ` +
                   `xlink:href="data:image/png;base64,${qrB64}"/>`);
        y += qrSize + 6;
        parts.push(`<text x="${W / 2}" y="${y + 18}" font-family="${FONT}" ` +
                   `font-size="18" fill="black" text-anchor="middle">${escapeXml(d.dec_id || '')}</text>`);
        y += LINE;
    }

    y += PAD;
    const H = y;

    const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <rect width="100%" height="100%" fill="white"/>
  ${parts.join('\n  ')}
</svg>`;

    // Render SVG → raw grayscale bytes
    const { data, info } = await sharp(Buffer.from(svg))
        .grayscale()
        .raw()
        .toBuffer({ resolveWithObject: true });

    return { gray: data, width: info.width, height: info.height };
}

module.exports = { renderReceiptGrayscale, W };
