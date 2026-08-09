"use client";

import { BanknotesIcon, CheckCircleIcon, ClipboardDocumentCheckIcon } from "@heroicons/react/24/outline";
import { formatCurrency } from "@/lib/imei";
import type { PageId, TaxResult } from "@/lib/types";
import { Button, Card, EmptyState, StatusBadge } from "./ui";

export function PayCenter({ rows, onNavigate, onPay, onCheck }: { rows: TaxResult[]; onNavigate: (page: PageId) => void; onPay: (id: string) => void; onCheck: (id: string) => void }) {
  const pending = rows.filter((row) => row.status === "Pending");
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">Payment workflow</p><h1>Pay Center</h1><p>Review and complete pending CEIR tax declarations.</p></div></div>
      <div className="pay-summary"><Card><BanknotesIcon /><div><span>Pending amount</span><strong>{formatCurrency(pending.reduce((sum, row) => sum + row.total, 0))} MMK</strong></div></Card><Card><ClipboardDocumentCheckIcon /><div><span>Ready to pay</span><strong>{pending.length} declarations</strong></div></Card><Card><CheckCircleIcon /><div><span>Completed</span><strong>{rows.filter((row) => row.status === "Paid").length} payments</strong></div></Card></div>
      <Card>
        <div className="card-title-row"><div><h2>Payment queue</h2><p>Payments are processed one declaration at a time.</p></div></div>
        {pending.length ? <div className="payment-list">{pending.map((row, index) => <div className="payment-row" key={row.id}><span className="queue-number">{String(index + 1).padStart(2, "0")}</span><div className="payment-main"><strong>{row.declarationId}</strong><span className="mono">{row.imei1}{row.imei2 ? ` · ${row.imei2}` : ""}</span></div><StatusBadge tone="warning">Pending</StatusBadge><strong className="payment-amount">{formatCurrency(row.total)} MMK</strong><Button className="ghost" onClick={() => void onCheck(row.id)}>Check status</Button><Button className="primary" onClick={() => onPay(row.id)}>Pay now</Button></div>)}</div> : <div><EmptyState icon={<CheckCircleIcon />} title="Payment queue is clear" copy="There are no pending declarations right now." /><div className="empty-action"><Button className="primary-soft" onClick={() => onNavigate("tax")}>Go to Tax Register</Button></div></div>}
      </Card>
    </div>
  );
}
