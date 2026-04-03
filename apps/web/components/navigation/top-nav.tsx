"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/analytics", label: "Analytics" },
  { href: "/backtests", label: "Backtests" },
  { href: "/strategies", label: "Strategies" },
  { href: "/risk", label: "Risk" },
  { href: "/trades", label: "Trades" },
  { href: "/settings", label: "Settings" }
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary navigation" className="w-full md:w-auto">
      <div className="flex w-full justify-start md:justify-center">
        <div className="inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-lg border border-[var(--line-soft)] bg-[var(--panel-soft)] p-0.5">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-chip whitespace-nowrap ${isActive ? "nav-chip-active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
