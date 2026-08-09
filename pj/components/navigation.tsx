"use client";

import {
  ArrowPathIcon,
  BanknotesIcon,
  Bars3Icon,
  ChartBarSquareIcon,
  CheckCircleIcon,
  ClipboardDocumentCheckIcon,
  Cog6ToothIcon,
  DevicePhoneMobileIcon,
  MoonIcon,
  SunIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import type { PageId } from "@/lib/types";
import { Button } from "./ui";

const navItems: Array<{ id: PageId; label: string; icon: typeof ChartBarSquareIcon }> = [
  { id: "home", label: "Dashboard", icon: ChartBarSquareIcon },
  { id: "imei", label: "IMEI Check", icon: DevicePhoneMobileIcon },
  { id: "tax", label: "Tax Register", icon: ClipboardDocumentCheckIcon },
  { id: "pay", label: "Pay Center", icon: BanknotesIcon },
];

export function Sidebar({ page, open, onNavigate, onClose }: { page: PageId; open: boolean; onNavigate: (page: PageId) => void; onClose: () => void }) {
  const navigate = (target: PageId) => {
    onNavigate(target);
    onClose();
  };

  return (
    <>
      {open && <button className="sidebar-scrim" aria-label="Close navigation" onClick={onClose} />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-block">
          <span className="brand-mark">C</span>
          <div><strong>CEIR</strong><span>Workspace</span></div>
          <button className="mobile-close" onClick={onClose} aria-label="Close menu"><XMarkIcon /></button>
        </div>
        <p className="nav-label">Workspace</p>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => navigate(item.id)}>
                <Icon /><span>{item.label}</span>
                {item.id === "pay" && <span className="nav-dot" />}
              </button>
            );
          })}
        </nav>
        <p className="nav-label settings-label">System</p>
        <nav className="nav-list">
          <button className={page === "settings" ? "active" : ""} onClick={() => navigate("settings")}>
            <Cog6ToothIcon /><span>Settings</span>
          </button>
        </nav>
        <div className="sidebar-card">
          <CheckCircleIcon />
          <div><strong>Browser worker</strong><span>Persistent CEIR session</span></div>
        </div>
        <div className="sidebar-footer"><span>CEIR Web</span><span>v1.0.0</span></div>
      </aside>
    </>
  );
}

export function Topbar({ dark, connection, onToggleDark, onMenu, onReconnect }: { dark: boolean; connection: "checking" | "connected" | "error"; onToggleDark: () => void; onMenu: () => void; onReconnect: () => void }) {
  return (
    <header className="topbar">
      <button className="menu-button" onClick={onMenu} aria-label="Open navigation"><Bars3Icon /></button>
      <div className={`connection connection-${connection}`}><span className="live-dot" /><div><strong>{connection === "connected" ? "CEIR connected" : connection === "checking" ? "Checking CEIR…" : "CEIR unavailable"}</strong><span>{connection === "connected" ? "Live browser session" : connection === "checking" ? "Starting browser worker" : "Open activity for details"}</span></div></div>
      <div className="topbar-spacer" />
      <div className="credit-chip"><BanknotesIcon /><span>Mode</span><strong>Live CEIR</strong></div>
      <Button className="icon-button" title="Reconnect" onClick={onReconnect}><ArrowPathIcon /></Button>
      <Button className="icon-button" title="Toggle theme" onClick={onToggleDark}>{dark ? <SunIcon /> : <MoonIcon />}</Button>
      <div className="avatar">LT</div>
    </header>
  );
}
