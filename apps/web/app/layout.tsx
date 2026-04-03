import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/auth/app-shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Theta Trading Dashboard",
  description: "Paper-only research and backtesting operations view"
};

export default function RootLayout({
  children
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
