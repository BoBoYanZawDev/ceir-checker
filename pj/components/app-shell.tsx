"use client";

import { useEffect, useMemo, useState } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";
import { Dashboard } from "./dashboard";
import { ImeiCheck } from "./imei-check";
import { PayCenter } from "./pay-center";
import { Settings } from "./settings";
import { TaxRegister } from "./tax-register";
import { Sidebar, Topbar } from "./navigation";
import { parseImeiText } from "@/lib/imei";
import type { Activity, Applicant, ImeiResult, PageId, TaxResult } from "@/lib/types";

const defaultApplicant: Applicant = {
  nationalId: "", fullName: "", birthday: "", phone: "", address: "", email: "", division: "", officeCode: "",
};

export function AppShell() {
  const [page, setPage] = useState<PageId>("home");
  const [dark, setDark] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [logOpen, setLogOpen] = useState(true);
  const [imeiInput, setImeiInput] = useState("");
  const [imeiResults, setImeiResults] = useState<ImeiResult[]>([]);
  const [taxInput, setTaxInput] = useState("");
  const [taxResults, setTaxResults] = useState<TaxResult[]>([]);
  const [applicant, setApplicant] = useState<Applicant>(defaultApplicant);
  const [busy, setBusy] = useState<"imei" | "tax" | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [connection, setConnection] = useState<"checking" | "connected" | "error">("checking");
  const [toast, setToast] = useState("");
  const [activities, setActivities] = useState<Activity[]>([
    { id: "1", at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), tone: "info", message: "Starting CEIR browser worker…" },
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const stored = window.localStorage.getItem("ceir-workspace-v2");
      if (stored) {
        try {
          const value = JSON.parse(stored) as { applicant?: Applicant; taxResults?: TaxResult[]; dark?: boolean };
          if (value.applicant) setApplicant(value.applicant);
          if (value.taxResults?.length) setTaxResults(value.taxResults);
          if (value.dark) setDark(true);
        } catch { /* Ignore malformed local state. */ }
      }
      setStorageReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!storageReady) return;
    window.localStorage.setItem("ceir-workspace-v2", JSON.stringify({ applicant, taxResults, dark }));
  }, [applicant, taxResults, dark, storageReady]);

  const activityCount = useMemo(() => activities.length, [activities]);
  const notify = (message: string, tone: Activity["tone"] = "info") => {
    setActivities((items) => [{ id: crypto.randomUUID(), at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), tone, message }, ...items]);
    setToast(message);
    window.setTimeout(() => setToast(""), 2300);
  };
  const readApi = async <T,>(response: Response): Promise<T> => {
    const data = await response.json() as T & { error?: string };
    if (!response.ok) throw new Error(data.error ?? `Request failed with HTTP ${response.status}`);
    return data;
  };
  const connect = async (reload = false) => {
    setConnection("checking");
    try {
      const response = await fetch(`/api/ceir/status${reload ? "?reload=1" : ""}`, { cache: "no-store" });
      const data = await readApi<{ ok: boolean; status: number }>(response);
      if (!data.ok) throw new Error(`ALTCHA health check returned HTTP ${data.status}`);
      setConnection("connected"); notify("CEIR browser session is ready", "success");
    } catch (error) {
      setConnection("error"); notify(error instanceof Error ? error.message : "CEIR connection failed", "warning");
    }
  };
  useEffect(() => {
    const timer = window.setTimeout(() => void connect(), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const runImei = async () => {
    setBusy("imei");
    try {
      const response = await fetch("/api/ceir/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pairs: parseImeiText(imeiInput) }) });
      const data = await readApi<{ ok: true; results: Array<Omit<ImeiResult, "payment1" | "payment2" | "block" | "status"> & { payment1: string; payment2: string; block: string; status: string }> }>(response);
      const rows: ImeiResult[] = data.results.map((row) => ({ ...row, payment1: row.payment1 === "PAID" ? "Paid" : row.payment1 === "UNPAID" ? "Unpaid" : "Failed", payment2: !row.payment2 ? "—" : row.payment2 === "PAID" ? "Paid" : row.payment2 === "UNPAID" ? "Unpaid" : "Failed", block: row.block === "UNBLOCKED" ? "Unblocked" : row.block === "BLOCKED" ? "Blocked" : row.block ? "Blocked" : "—", status: row.status === "OK" ? "Complete" : "Failed" }));
      setImeiResults(rows);
      notify(`${rows.length} IMEI ${rows.length === 1 ? "device" : "devices"} checked`, "success");
      setConnection("connected");
    } catch (error) { setConnection("error"); notify(error instanceof Error ? error.message : "IMEI check failed", "warning"); }
    finally { setBusy(null); }
  };
  const runTax = async () => {
    setBusy("tax");
    try {
      const response = await fetch("/api/ceir/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pairs: parseImeiText(taxInput), applicant }) });
      const data = await readApi<{ ok: true; registered: TaxResult[] }>(response);
      const rows = data.registered;
      setTaxResults((current) => [...rows, ...current]);
      notify(`${rows.filter((row) => row.status !== "Failed").length} declarations created`, "success");
      setConnection("connected");
    } catch (error) { setConnection("error"); notify(error instanceof Error ? error.message : "Tax registration failed", "warning"); }
    finally { setBusy(null); }
  };
  const startPayment = (id: string) => {
    const row = taxResults.find((item) => item.id === id);
    if (!row || row.declarationId === "—") return;
    window.open(`/api/ceir/payment/init?declarationId=${encodeURIComponent(row.declarationId)}`, "_blank", "noopener,noreferrer");
    notify(`Opening IRD payment for ${row.declarationId}`);
  };
  const checkPayment = async (id: string) => {
    const row = taxResults.find((item) => item.id === id);
    if (!row) return;
    try {
      const response = await fetch("/api/ceir/payment/status", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ declarationId: row.declarationId }) });
      const data = await readApi<{ ok: true; businessState: string }>(response);
      setTaxResults((rows) => rows.map((item) => item.id === id ? { ...item, status: data.businessState === "PAID" ? "Paid" : "Pending" } : item));
      notify(`${row.declarationId}: ${data.businessState}`, data.businessState === "PAID" ? "success" : "info");
    } catch (error) { notify(error instanceof Error ? error.message : "Payment check failed", "warning"); }
  };

  return (
    <div className={dark ? "app dark" : "app"}>
      <Sidebar page={page} open={mobileNav} onNavigate={setPage} onClose={() => setMobileNav(false)} />
      <div className="workspace">
        <Topbar dark={dark} connection={connection} onToggleDark={() => setDark(!dark)} onMenu={() => setMobileNav(true)} onReconnect={() => void connect(true)} />
        <main className="content">
          {page === "home" && <Dashboard taxRows={taxResults} onNavigate={setPage} />}
          {page === "imei" && <ImeiCheck input={imeiInput} results={imeiResults} busy={busy === "imei"} onInput={setImeiInput} onStart={runImei} onClear={() => setImeiResults([])} />}
          {page === "tax" && <TaxRegister applicant={applicant} input={taxInput} results={taxResults} busy={busy === "tax"} onApplicant={setApplicant} onInput={setTaxInput} onStart={() => void runTax()} onClear={() => setTaxResults([])} onPay={startPayment} />}
          {page === "pay" && <PayCenter rows={taxResults} onNavigate={setPage} onPay={startPayment} onCheck={checkPayment} />}
          {page === "settings" && <Settings />}
        </main>
      </div>
      <aside className={`activity-drawer ${logOpen ? "open" : ""}`}>
        <button className="activity-tab" onClick={() => setLogOpen(!logOpen)}><span className="live-dot" />Activity <b>{activityCount}</b></button>
        <div className="drawer-head"><div><strong>Live activity</strong><span>Session events and updates</span></div><button onClick={() => setLogOpen(false)} aria-label="Close activity"><XMarkIcon /></button></div>
        <div className="drawer-list">{activities.map((item) => <div className="drawer-item" key={item.id}><i className={item.tone} /><div><span>{item.message}</span><time>{item.at}</time></div></div>)}</div>
      </aside>
      {toast && <div className="toast"><span>✓</span>{toast}</div>}
    </div>
  );
}
