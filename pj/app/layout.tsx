import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CEIR Workspace",
  description: "IMEI verification and tax registration workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
