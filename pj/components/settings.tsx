"use client";

import { CheckIcon, ClipboardIcon, PrinterIcon } from "@heroicons/react/24/outline";
import { useState } from "react";
import { Button, Card } from "./ui";

export function Settings() {
  const [saved, setSaved] = useState(false);
  const [batch, setBatch] = useState("5");
  const [delay, setDelay] = useState("2");
  const save = () => { setSaved(true); window.setTimeout(() => setSaved(false), 1800); };
  return <div className="page-stack settings-page">
    <div className="page-heading"><div><p className="eyebrow">Configuration</p><h1>Settings</h1><p>Manage workflow timing, printer, account and license details.</p></div><Button className="primary" onClick={save}>{saved ? <CheckIcon /> : null}{saved ? "Saved" : "Save changes"}</Button></div>
    <Card><div className="settings-title"><h2>IMEI check timing</h2><p>Control the workload sent to CEIR for each request.</p></div><div className="form-grid settings-grid"><Field label="Phones per API call" value={batch} onChange={setBatch} type="number" /><Field label="Delay between batches (seconds)" value={delay} onChange={setDelay} type="number" /><Field label="Request timeout (seconds)" value="30" /><Field label="Tax register delay (seconds)" value="3" /></div></Card>
    <Card><div className="settings-title icon-title"><span><PrinterIcon /></span><div><h2>Receipt printer</h2><p>Brother QL printers are supported by the desktop bridge.</p></div></div><div className="form-grid settings-grid"><Field label="Printer name" value="Brother_QL_820NWB" /><Field label="Label width (mm)" value="62" /></div><Button className="ghost">Detect printer</Button></Card>
    <Card><div className="settings-title"><h2>License & account</h2><p>This web rewrite keeps machine-bound features isolated from the interface.</p></div><div className="license-row"><div><span>Signed-in account</span><strong>Linn Thant · linn@example.com</strong></div><div><span>License status</span><strong className="license-active"><i />Active until 6 Aug 2027</strong></div><div><span>Machine ID</span><strong className="mono">CEIR-WEB-7D9A-24F1</strong></div><Button className="ghost" onClick={() => navigator.clipboard?.writeText("CEIR-WEB-7D9A-24F1")}><ClipboardIcon />Copy</Button></div></Card>
  </div>;
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange?: (value: string) => void; type?: string }) {
  return <label className="field"><span>{label}</span><input type={type} value={value} onChange={(event) => onChange?.(event.target.value)} readOnly={!onChange} /></label>;
}
