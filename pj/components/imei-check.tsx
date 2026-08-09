"use client";

import { ArrowDownTrayIcon, ArrowPathIcon, DocumentArrowUpIcon, PlayIcon, TrashIcon } from "@heroicons/react/24/outline";
import type { ChangeEvent } from "react";
import type { ImeiResult } from "@/lib/types";
import { parseImeiText } from "@/lib/imei";
import { Button, Card, EmptyState, StatusBadge } from "./ui";

export function ImeiCheck({ input, results, busy, onInput, onStart, onClear }: { input: string; results: ImeiResult[]; busy: boolean; onInput: (value: string) => void; onStart: () => void; onClear: () => void }) {
  const count = parseImeiText(input).length;
  const loadFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    file.text().then(onInput);
  };
  const download = () => {
    const csv = ["IMEI 1,IMEI 2,Device,Payment 1,Payment 2,Block,Status", ...results.map((row) => [row.imei1, row.imei2, row.device, row.payment1, row.payment2, row.block, row.status].join(","))].join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    link.download = "ceir-imei-results.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  };
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Verification workflow</p><h1>IMEI Check</h1><p>Verify payment and block status for multiple devices.</p></div></div>
      <Card>
        <div className="card-title-row"><div><h2>IMEI input</h2><p>Enter one device per line. Separate dual IMEIs with a comma.</p></div><span className="count-pill">{count} {count === 1 ? "device" : "devices"}</span></div>
        <textarea className="imei-textarea" value={input} onChange={(event) => onInput(event.target.value)} placeholder={"353456789012345, 353456789012346\n357440806712128\n# comments are ignored"} />
        <div className="toolbar"><label className="button file-button"><DocumentArrowUpIcon />Load file<input type="file" accept=".txt,.csv" onChange={loadFile} /></label><span className="toolbar-hint">TXT and CSV supported</span><div className="grow" /><Button className="ghost" onClick={() => onInput("")}>Clear input</Button><Button className="primary" disabled={!count || busy} onClick={onStart}>{busy ? <ArrowPathIcon className="spin" /> : <PlayIcon />}{busy ? "Checking…" : "Start check"}</Button></div>
      </Card>
      <Card>
        <div className="card-title-row"><div><h2>Results</h2><p>{results.length ? `${results.filter((row) => row.status === "Complete").length} completed · ${results.filter((row) => row.status === "Failed").length} failed` : "Results will appear here after a check"}</p></div><div className="row-actions"><Button className="ghost" disabled={!results.length} onClick={onClear}><TrashIcon />Clear</Button><Button className="ghost" disabled={!results.length} onClick={onStart}><ArrowPathIcon />Re-check</Button><Button className="primary-soft" disabled={!results.length} onClick={download}><ArrowDownTrayIcon />Export CSV</Button></div></div>
        {results.length ? <div className="table-scroll"><table><thead><tr><th>IMEI 1</th><th>IMEI 2</th><th>Brand / model</th><th>Payment</th><th>Block</th><th>Status</th></tr></thead><tbody>{results.map((row) => <tr key={row.id}><td className="mono">{row.imei1}</td><td className="mono muted">{row.imei2 || "—"}</td><td>{row.device}</td><td><StatusBadge tone={row.payment1 === "Paid" ? "success" : row.payment1 === "Unpaid" ? "warning" : "danger"}>{row.payment1}</StatusBadge></td><td>{row.block}</td><td><StatusBadge tone={row.status === "Complete" ? "success" : "danger"}>{row.status}</StatusBadge></td></tr>)}</tbody></table></div> : <EmptyState icon={<DevicePhoneMobileIcon />} title="No results yet" copy="Add IMEI numbers above and start a check." />}
      </Card>
    </div>
  );
}

function DevicePhoneMobileIcon() { return <span className="phone-glyph">⌕</span>; }
