import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/auth/app-shell";
import { ThemeProvider } from "@/components/theme/theme-provider";
import { buildThemeInitScript } from "@/lib/theme";

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
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          id="theme-init"
          dangerouslySetInnerHTML={{ __html: buildThemeInitScript() }}
        />
      </head>
      <body>
        <ThemeProvider>
          <AppShell>{children}</AppShell>
        </ThemeProvider>
      </body>
    </html>
  );
}
