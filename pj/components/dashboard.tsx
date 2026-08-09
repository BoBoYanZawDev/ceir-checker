"use client";

import { ArrowRightIcon, BanknotesIcon, CheckCircleIcon, ClipboardDocumentCheckIcon, DevicePhoneMobileIcon, ExclamationTriangleIcon } from "@heroicons/react/24/outline";
import type { PageId, TaxResult } from "@/lib/types";
import { Button, Card } from "./ui";

const chartData = [42, 54, 38, 68, 60, 78, 64];
const days = ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"];

export function Dashboard({ taxRows, onNavigate }: { taxRows: TaxResult[]; onNavigate: (page: PageId) => void }) {
  const paid = taxRows.filter((row) => row.status === "Paid").length;
  const pending = taxRows.filter((row) => row.status === "Pending").length;
  return (
    <div className="page-stack">
      <div className="welcome-row">
        <div><p className="eyebrow">Thursday, 6 August</p><h1>Good morning, Linn.</h1><p>Here&apos;s what&apos;s happening with your CEIR workspace today.</p></div>
        <Button className="primary" onClick={() => onNavigate("imei")}><DevicePhoneMobileIcon />New IMEI check</Button>
      </div>

      <div className="metric-grid">
        <Metric label="Total processed" value={String(taxRows.length)} delta="Saved declarations" icon={<ClipboardDocumentCheckIcon />} tone="blue" />
        <Metric label="Registered" value={String(taxRows.filter((row) => row.status !== "Failed").length)} delta="Live CEIR results" icon={<CheckCircleIcon />} tone="green" />
        <Metric label="Pending payment" value={String(pending)} delta={pending ? "Needs attention" : "Queue is clear"} icon={<ExclamationTriangleIcon />} tone="orange" />
        <Metric label="Paid" value={String(paid)} delta={`${taxRows.filter((row) => row.status === "Paid").reduce((sum, row) => sum + row.total, 0).toLocaleString()} MMK`} icon={<BanknotesIcon />} tone="violet" />
      </div>

      <div className="dashboard-grid">
        <Card className="performance-card">
          <div className="card-title-row"><div><h2>Weekly performance</h2><p>Completed registrations over the last 7 days</p></div><span className="trend">↗ 8.4%</span></div>
          <div className="chart">
            {chartData.map((value, index) => <div className="chart-column" key={days[index]}><div className="bar-track"><span style={{ height: `${value}%` }} /></div><small>{days[index]}</small></div>)}
          </div>
        </Card>
        <Card className="quick-card">
          <div className="card-title-row"><div><h2>Quick actions</h2><p>Start your common workflows</p></div></div>
          <QuickAction icon={<DevicePhoneMobileIcon />} title="Check IMEI numbers" copy="Verify device registration and payment status" onClick={() => onNavigate("imei")} tone="blue" />
          <QuickAction icon={<ClipboardDocumentCheckIcon />} title="Register for tax" copy="Create declarations for imported devices" onClick={() => onNavigate("tax")} tone="violet" />
          <QuickAction icon={<BanknotesIcon />} title="Open Pay Center" copy="Complete pending declaration payments" onClick={() => onNavigate("pay")} tone="green" />
        </Card>
      </div>

      <Card>
        <div className="card-title-row"><div><h2>Recent activity</h2><p>Your latest registrations and checks</p></div><Button className="text-button" onClick={() => onNavigate("tax")}>View all <ArrowRightIcon /></Button></div>
        <div className="activity-list">
          {[
            ["MM-CR-928104", "2 devices registered", "Just now", "Pending"],
            ["MM-CR-928081", "Payment confirmed", "18 minutes ago", "Paid"],
            ["IMEI batch #1042", "12 devices checked", "41 minutes ago", "Complete"],
          ].map(([name, desc, time, status]) => <div className="activity-row" key={name}><div className="activity-symbol"><ClipboardDocumentCheckIcon /></div><div className="activity-main"><strong>{name}</strong><span>{desc}</span></div><time>{time}</time><span className={`status-text ${status.toLowerCase()}`}>{status}</span></div>)}
        </div>
      </Card>
    </div>
  );
}

function Metric({ label, value, delta, icon, tone }: { label: string; value: string; delta: string; icon: React.ReactNode; tone: string }) {
  return <Card className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><p>{label}</p><strong>{value}</strong><span>{delta}</span></Card>;
}

function QuickAction({ icon, title, copy, onClick, tone }: { icon: React.ReactNode; title: string; copy: string; onClick: () => void; tone: string }) {
  return <button className="quick-action" onClick={onClick}><span className={`quick-icon ${tone}`}>{icon}</span><span><strong>{title}</strong><small>{copy}</small></span><ArrowRightIcon /></button>;
}
