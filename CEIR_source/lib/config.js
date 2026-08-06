// Persistent config in app.getPath('userData')/config.json
const fs   = require('fs');
const path = require('path');
const { app } = require('electron');

const DEFAULTS = {
  // IMEI Check
  batch_size:          5,
  ceir_check_delay_sec: 2,
  req_timeout:         20,
  // CF / Browser
  cf_wait_sec:         90,
  // Tax
  tax_req_delay_sec:   3,
  // Applicant
  applicant: {
    nationalId: '', fullName: '', birthday: '',
    address: '', email: '', phone: '',
    taxOfficeDivision: '', taxOfficeCode: '',
  },
  // Print
  brother_printer_name: '',
  brother_label_size:   '62',
  // Pay Center automation
  bank_account:    '',      // UAB account number auto-filled into the IRD page
  pay_autofill:    false,   // auto-select UAB + fill account + request OTP
  pay_auto_otp:    true,    // auto-fill OTP forwarded from the phone
  otp_listen_port: 8377,    // LAN port MacroDroid posts forwarded SMS to
  otp_secret:      '',      // shared secret, auto-generated on first launch
};

function configPath() {
  return path.join(app.getPath('userData'), 'config.json');
}
function load() {
  try {
    const raw = fs.readFileSync(configPath(), 'utf8');
    const obj = JSON.parse(raw);
    return { ...DEFAULTS, ...obj, applicant: { ...DEFAULTS.applicant, ...(obj.applicant || {}) } };
  } catch (e) {
    return { ...DEFAULTS };
  }
}
function save(cfg) {
  try {
    fs.mkdirSync(path.dirname(configPath()), { recursive: true });
    fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2));
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

module.exports = { load, save, DEFAULTS };
