// Excel I/O for IMEI Check + Tax Register.
// Format mirrors the PyQt openpyxl output exactly (header colors, stripes,
// borders, freeze panes, auto-filter) so files look the same as before.
const ExcelJS = require('exceljs');
const fs      = require('fs');

// ── Common style helpers ────────────────────────────────────────────────────
const FONT_H   = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11, name: 'Arial' };
const FONT_B   = { size: 10, name: 'Arial' };
const ALIGN_C  = { horizontal: 'center', vertical: 'middle' };
const ALIGN_L  = { horizontal: 'left',   vertical: 'middle' };
const thinSide = { style: 'thin', color: { argb: 'FFD9D9D9' } };
const BORDER   = { left: thinSide, right: thinSide, top: thinSide, bottom: thinSide };

function fill(argb) { return { type: 'pattern', pattern: 'solid', fgColor: { argb } }; }

const PASS_FILL  = fill('FFD5F5D5'); const PASS_FONT = { bold: true, size: 10, name: 'Arial', color: { argb: 'FF1A7F37' } };
const FAIL_FILL  = fill('FFFFD7D5'); const FAIL_FONT = { bold: true, size: 10, name: 'Arial', color: { argb: 'FFCF222E' } };
const STRIPE_E   = fill('FFF2F2F2'); const STRIPE_O  = fill('FFFFFFFF');

// ── IMEI input parsing ─────────────────────────────────────────────────────
async function importImeiFile(path) {
    const lower = path.toLowerCase();
    if (lower.endsWith('.xlsx')) {
        const wb = new ExcelJS.Workbook();
        await wb.xlsx.readFile(path);
        const ws = wb.worksheets[0];
        const pairs = [];
        let firstRow = true;
        ws.eachRow((row) => {
            const a = String(row.getCell(1).value || '').trim();
            const b = String(row.getCell(2).value || '').trim();
            if (firstRow) {
                firstRow = false;
                if (!/^\d{14,17}$/.test(a)) return;
            }
            if (/^\d{14,17}$/.test(a)) {
                pairs.push({ imei1: a, imei2: /^\d{14,17}$/.test(b) ? b : null });
            }
        });
        return pairs;
    }
    return parseImeiText(fs.readFileSync(path, 'utf8'));
}

function parseImeiText(text) {
    const pairs = [];
    for (const raw of (text || '').split('\n')) {
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;
        const parts = line.replace(/\t/g, ',').split(',')
            .map(s => s.trim()).filter(s => /^\d+$/.test(s));
        if (parts.length >= 2)      pairs.push({ imei1: parts[0], imei2: parts[1] });
        else if (parts.length === 1) pairs.push({ imei1: parts[0], imei2: null });
    }
    return pairs;
}

// ── IMEI Check export — matches PyQt _export_excel ─────────────────────────
function isFailRow(r) {
    if (r.status !== 'OK') return true;
    if (r.payment1 && !['PAID','ACCUMULATION',''].includes(r.payment1)) return true;
    if (r.imei2 && r.payment2 && !['PAID','ACCUMULATION',''].includes(r.payment2)) return true;
    if (r.blockState && !['UNBLOCKED','UNBLOCKED/UNBLOCKED',''].includes(r.blockState)) return true;
    return false;
}

async function exportImeiResults(path, results, label = 'ceir_results') {
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('CEIR Results', {
        views: [{ state: 'frozen', ySplit: 2 }]
    });

    const total = results.length;
    const failC = results.filter(isFailRow).length;

    // Title row
    ws.mergeCells('A1:I1');
    const t = ws.getCell('A1');
    t.value = `${label.replace(/_/g, ' ').toUpperCase()}  —  Total:${total}  Pass:${total - failC}  Fail:${failC}`;
    t.font  = { bold: true, size: 13, name: 'Arial', color: { argb: 'FF2F5496' } };
    t.alignment = ALIGN_L;
    ws.getRow(1).height = 30;

    // Headers — Brand/Model column inserted between IMEI 2 and Payment 1
    const headers = ['No','IMEI 1','IMEI 2','Brand / Model','Payment 1','Payment 2','Block State','Status','Result'];
    const widths  = [6, 20, 20, 26, 14, 14, 22, 10, 10];
    headers.forEach((h, i) => {
        const c = ws.getCell(2, i + 1);
        c.value = h; c.font = FONT_H;
        c.fill = fill('FF2F5496');
        c.alignment = ALIGN_C; c.border = BORDER;
        ws.getColumn(i + 1).width = widths[i];
    });
    ws.getRow(2).height = 24;

    // Body rows
    results.forEach((r, i) => {
        const rn   = i + 3;
        const fail = isFailRow(r);
        const stripe = (i % 2 === 1) ? STRIPE_E : STRIPE_O;
        const brandModel = [r.brand, r.model].filter(Boolean).join(' ').trim();
        const rowData = [
            i + 1, r.imei1, r.imei2 || '',
            brandModel,
            r.payment1, r.payment2 || '', r.blockState || '',
            r.status, fail ? 'FAIL' : 'PASS',
        ];
        rowData.forEach((val, ci) => {
            const col = ci + 1;
            const c   = ws.getCell(rn, col);
            c.value = val; c.font = FONT_B; c.alignment = ALIGN_C; c.border = BORDER;
            // Columns shifted by +1 since Brand/Model is col 4 now:
            //   1 No, 2 IMEI1, 3 IMEI2, 4 Brand/Model,
            //   5 Payment1, 6 Payment2, 7 Block, 8 Status, 9 Result
            if (col >= 5) {
                const cf = (
                    (col === 5 && val && !['ACCUMULATION','PAID',''].includes(val)) ||
                    (col === 6 && val && !['ACCUMULATION','PAID',''].includes(val)) ||
                    (col === 7 && val && !['UNBLOCKED','UNBLOCKED/UNBLOCKED',''].includes(val)) ||
                    (col === 8 && val !== 'OK') ||
                    (col === 9 && fail)
                );
                c.fill = cf ? FAIL_FILL : PASS_FILL;
                c.font = cf ? FAIL_FONT : PASS_FONT;
            } else if (col === 4) {
                c.alignment = ALIGN_L;
                c.fill = fail ? FAIL_FILL : stripe;
            } else {
                c.fill = fail ? FAIL_FILL : stripe;
            }
        });
    });

    // Auto-filter
    ws.autoFilter = { from: { row: 2, column: 1 }, to: { row: total + 2, column: 9 } };

    await wb.xlsx.writeFile(path);
}

// ── Tax Register export — matches PyQt _export_tax_excel ───────────────────
async function exportTaxResults(path, results) {
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Tax Results', {
        views: [{ state: 'frozen', ySplit: 2 }]
    });

    const total = results.length;
    const ok    = results.filter(r => r.status === 'OK').length;
    const paid  = results.filter(r => r.pay_status === 'PAID').length;

    // Title
    ws.mergeCells('A1:J1');
    const t = ws.getCell('A1');
    t.value = `CEIR TAX REGISTRATION RESULTS  —  Total:${total}  OK:${ok}  Paid:${paid}  Failed:${total - ok}`;
    t.font  = { bold: true, size: 13, name: 'Arial', color: { argb: 'FF8B6914' } };
    t.alignment = ALIGN_L;
    ws.getRow(1).height = 30;

    const headers = ['No','IMEI 1','IMEI 2','Declaration ID','Total (MMK)','Customs Duty','Commercial Tax','Redemption Fine','Reg Status','Pay Status'];
    const widths  = [5, 20, 20, 22, 14, 14, 14, 14, 12, 12];
    headers.forEach((h, i) => {
        const c = ws.getCell(2, i + 1);
        c.value = h; c.font = FONT_H;
        c.fill = fill('FF8B6914');
        c.alignment = ALIGN_C; c.border = BORDER;
        ws.getColumn(i + 1).width = widths[i];
    });
    ws.getRow(2).height = 24;

    results.forEach((r, i) => {
        const rn   = i + 3;
        const okRow = r.status === 'OK';
        const stripe = (i % 2 === 1) ? STRIPE_E : STRIPE_O;
        const fineVal = r.fine || 0;
        const rowData = [
            i + 1, r.imei1, r.imei2 || '', r.declaration_id || '',
            r.amount || '', r.customs || '', r.commercial || '',
            fineVal || '',
            r.status, r.pay_status || '',
        ];
        rowData.forEach((val, ci) => {
            const col = ci + 1;
            const c = ws.getCell(rn, col);
            c.value = val; c.font = FONT_B; c.alignment = ALIGN_C; c.border = BORDER;

            if (col === 9) {
                // Reg Status: green if OK, red otherwise
                c.fill = okRow ? PASS_FILL : FAIL_FILL;
                c.font = okRow ? PASS_FONT : FAIL_FONT;
            } else if (col === 10) {
                // Pay Status: green if PAID, red if error, stripe if PENDING
                const isPaid = (val === 'PAID');
                if (isPaid) { c.fill = PASS_FILL; c.font = PASS_FONT; }
                else if (val && val !== 'PENDING') { c.fill = FAIL_FILL; c.font = FAIL_FONT; }
                else { c.fill = stripe; }
            } else if (col === 4) {
                // Declaration ID — green if OK
                c.fill = okRow ? PASS_FILL : FAIL_FILL;
                c.font = okRow ? PASS_FONT : FAIL_FONT;
            } else if (col === 8 && fineVal) {
                // Redemption Fine — red highlight when non-zero
                c.fill = FAIL_FILL;
                c.font = FAIL_FONT;
            } else {
                c.fill = stripe;
            }
        });
    });

    await wb.xlsx.writeFile(path);
}

async function importTaxResults(path) {
    const wb = new ExcelJS.Workbook();
    await wb.xlsx.readFile(path);
    const ws = wb.worksheets[0];
    const out = [];
    ws.eachRow((row, rn) => {
        if (rn < 3) return;
        const v = (i) => {
            const cell = row.getCell(i).value;
            if (cell === null || cell === undefined) return '';
            return typeof cell === 'object' && cell.text ? String(cell.text) : String(cell);
        };
        const imei1 = v(2).trim();
        const dec_id = v(4).trim();
        if (!imei1 && !dec_id) return;
        const num = (s) => {
            const n = parseInt(String(s).replace(/,/g, ''), 10);
            return isNaN(n) ? 0 : n;
        };
        out.push({
            imei1, imei2: v(3).trim() || null,
            declaration_id: dec_id,
            amount:     num(v(5)),
            customs:    num(v(6)),
            commercial: num(v(7)),
            fine:       num(v(8)),
            status:     v(9).trim() || 'OK',
            pay_status: v(10).trim() || 'PENDING',
            print_flag: true,
        });
    });
    return out;
}

// ── Fail list .txt export ──────────────────────────────────────────────────
function exportFailList(path, results) {
    const fails = [];
    for (const r of results) {
        if (!isFailRow(r)) continue;
        if (r.payment1 && r.payment1 !== 'PAID' && r.payment1 !== 'ACCUMULATION') fails.push(r.imei1);
        if (r.imei2 && r.payment2 && r.payment2 !== 'PAID' && r.payment2 !== 'ACCUMULATION') fails.push(r.imei2);
    }
    fs.writeFileSync(path, fails.join('\n'));
    return fails.length;
}

module.exports = {
    importImeiFile, parseImeiText,
    exportImeiResults, exportTaxResults, importTaxResults, exportFailList,
};
