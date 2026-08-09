"use client";

import { ArrowDownTrayIcon, ChevronDownIcon, ChevronUpIcon, DocumentArrowUpIcon, MagnifyingGlassIcon, PlayIcon, PrinterIcon, TrashIcon } from "@heroicons/react/24/outline";
import { useMemo, useState, type ChangeEvent } from "react";
import { formatCurrency, parseImeiText } from "@/lib/imei";
import type { Applicant, TaxResult } from "@/lib/types";
import { Button, Card, EmptyState, StatusBadge } from "./ui";

export function TaxRegister({ applicant, input, results, busy, onApplicant, onInput, onStart, onClear, onPay }: { applicant: Applicant; input: string; results: TaxResult[]; busy: boolean; onApplicant: (value: Applicant) => void; onInput: (value: string) => void; onStart: () => void; onClear: () => void; onPay: (id: string) => void }) {
  const [applicantOpen, setApplicantOpen] = useState(false);
  const [query, setQuery] = useState("");
  const count = parseImeiText(input).length;
  const filtered = useMemo(() => results.filter((row) => `${row.imei1} ${row.imei2} ${row.declarationId} ${row.status}`.toLowerCase().includes(query.toLowerCase())), [query, results]);
  const update = (key: keyof Applicant, value: string) => onApplicant({ ...applicant, [key]: value });
  const loadFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) file.text().then(onInput);
  };
  const exportRows = () => {
    const csv = ["IMEI 1,IMEI 2,Declaration ID,Total,Customs,Commercial,Fine,Status", ...results.map((row) => [row.imei1, row.imei2, row.declarationId, row.total, row.customs, row.commercial, row.fine, row.status].join(","))].join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "ceir-tax-declarations.csv"; link.click(); URL.revokeObjectURL(link.href);
  };
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Registration workflow</p><h1>Tax Register</h1><p>Generate declaration IDs and prepare device tax payments.</p></div><div className="step-indicator"><span className="done">1</span><i /><span className={results.length ? "done" : "current"}>2</span><i /><span>3</span></div></div>
      <Card className="accordion-card">
        <button className="accordion-head" onClick={() => setApplicantOpen(!applicantOpen)}><span className="step-number">1</span><span><strong>Applicant information</strong><small>{applicant.fullName ? `${applicant.fullName} · ${applicant.nationalId}` : "Add identity and tax office details"}</small></span><div className="grow" /><StatusBadge tone={applicant.fullName ? "success" : "neutral"}>{applicant.fullName ? "Saved" : "Required"}</StatusBadge>{applicantOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}</button>
        {applicantOpen && <div className="form-grid applicant-form">
          <Field label="National ID" value={applicant.nationalId} onChange={(v) => update("nationalId", v)} placeholder="5/မရန(N)329768" />
          <Field label="Full name" value={applicant.fullName} onChange={(v) => update("fullName", v)} placeholder="Full name" />
          <Field label="Birthday" type="date" value={applicant.birthday} onChange={(v) => update("birthday", v)} />
          <Field label="Phone" value={applicant.phone} onChange={(v) => update("phone", v)} placeholder="959XXXXXXXXX" />
          <Field label="Address" value={applicant.address} onChange={(v) => update("address", v)} placeholder="Yangon" />
          <Field label="Email" type="email" value={applicant.email} onChange={(v) => update("email", v)} placeholder="name@example.com" />
          <Field label="Tax division" value={applicant.division} onChange={(v) => update("division", v)} placeholder="MMR005" />
          <Field label="Office code" value={applicant.officeCode} onChange={(v) => update("officeCode", v)} placeholder="R05-03-MYN" />
        </div>}
      </Card>
      <Card>
        <div className="card-title-row"><div className="title-with-step"><span className="step-number">2</span><div><h2>Device IMEIs</h2><p>One phone per line; separate paired IMEIs with a comma.</p></div></div><span className="count-pill">{count} devices</span></div>
        <textarea className="imei-textarea compact" value={input} onChange={(event) => onInput(event.target.value)} placeholder={"860812086707350, 860812086707343\n353456789012345"} />
        <div className="toolbar"><label className="button file-button"><DocumentArrowUpIcon />Import<input type="file" accept=".txt,.csv" onChange={loadFile} /></label><div className="grow" /><Button className="ghost" onClick={() => onInput("")}>Clear</Button><Button className="warning-button" disabled={!count || busy} onClick={onStart}><PlayIcon />{busy ? "Registering…" : "Start register"}</Button></div>
      </Card>
      <Card>
        <div className="card-title-row"><div><h2>Declarations</h2><p>{results.length} records in this session</p></div><div className="row-actions"><label className="search-field"><MagnifyingGlassIcon /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search declarations" /></label><Button className="ghost" disabled={!results.length} onClick={onClear}><TrashIcon /></Button><Button className="primary-soft" disabled={!results.length} onClick={exportRows}><ArrowDownTrayIcon />Export</Button></div></div>
        {filtered.length ? <div className="table-scroll"><table><thead><tr><th>IMEI</th><th>Declaration ID</th><th>Total</th><th>Customs</th><th>Commercial</th><th>Fine</th><th>Status</th><th /></tr></thead><tbody>{filtered.map((row) => <tr key={row.id}><td><span className="mono">{row.imei1}</span><small className="table-sub">{row.imei2 || "Single SIM"}</small></td><td className="mono">{row.declarationId}</td><td className="amount">{formatCurrency(row.total)}</td><td>{formatCurrency(row.customs)}</td><td>{formatCurrency(row.commercial)}</td><td>{formatCurrency(row.fine)}</td><td><StatusBadge tone={row.status === "Paid" ? "success" : row.status === "Pending" ? "warning" : "danger"}>{row.status}</StatusBadge></td><td>{row.status === "Pending" && <Button className="table-button" onClick={() => onPay(row.id)}>Pay</Button>}{row.status === "Paid" && <PrinterIcon className="paid-icon" />}</td></tr>)}</tbody></table></div> : <EmptyState icon={<span className="document-glyph">▤</span>} title="No declarations yet" copy="Complete the applicant details, add device IMEIs, then start registration." />}
      </Card>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = "text" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return <label className="field"><span>{label}</span><input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}
