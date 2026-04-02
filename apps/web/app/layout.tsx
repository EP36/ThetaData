import type { Metadata } from "next";
import type { ReactNode } from "react";

import { TopNav } from "@/components/navigation/top-nav";

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
      <body>
        <div className="mx-auto flex min-h-screen w-full max-w-[1180px] flex-col px-4 pb-10 pt-5 sm:px-6 lg:px-8">
          <header className="glass-panel panel-animate sticky top-3 z-40 mb-6 flex flex-wrap items-center justify-between gap-4 rounded-3xl px-5 py-4 md:px-6">
            <div className="space-y-1">
              <p className="text-[0.66rem] font-semibold uppercase tracking-[0.26em] text-[var(--muted)]">
                Theta Data
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-lg font-semibold tracking-[-0.02em] sm:text-xl">
                  Trading Operations Console
                </h1>
                <span className="ui-pill border-[rgba(0,200,5,0.26)] bg-[var(--accent-soft)] text-[#0b4f12]">
                  Paper-Only
                </span>
              </div>
            </div>
            <TopNav />
          </header>
          <main className="flex-1 panel-animate pb-2">{children}</main>
        </div>
      </body>
    </html>
  );
}
