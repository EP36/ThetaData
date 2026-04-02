"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/backtests", label: "Backtests" },
  { href: "/strategies", label: "Strategies" },
  { href: "/risk", label: "Risk" },
  { href: "/trades", label: "Trades" }
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <nav className="flex max-w-full items-center gap-1 overflow-x-auto rounded-full bg-[var(--panel-soft)] p-1">
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
    </nav>
  );
}
