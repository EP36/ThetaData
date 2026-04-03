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

type TopNavProps = {
  userEmail?: string | null;
  userRole?: string | null;
  onLogout?: () => void | Promise<void>;
};

export function TopNav({ userEmail, userRole, onLogout }: TopNavProps) {
  const pathname = usePathname();

  return (
    <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
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
      <div className="flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--panel-soft)] px-3 py-1.5">
        <div className="text-right leading-tight">
          <p className="text-xs font-medium text-[var(--text)]">{userEmail ?? "Signed out"}</p>
          <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--muted)]">
            {userRole ?? "guest"}
          </p>
        </div>
        {onLogout ? (
          <button
            type="button"
            onClick={() => void onLogout()}
            className="ui-button px-3 py-1 text-xs"
          >
            Logout
          </button>
        ) : null}
      </div>
    </div>
  );
}
