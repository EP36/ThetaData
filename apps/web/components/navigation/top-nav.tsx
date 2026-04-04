"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type TopNavProps = {
  variant?: "desktop" | "mobile-secondary";
};

const coreNavHrefs = new Set(["/dashboard", "/trades", "/strategies", "/settings"]);
const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/analytics", label: "Analytics" },
  { href: "/backtests", label: "Backtests" },
  { href: "/strategies", label: "Strategies" },
  { href: "/risk", label: "Risk" },
  { href: "/trades", label: "Trades" },
  { href: "/settings", label: "Settings" }
];

function isRouteActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TopNav({ variant = "desktop" }: TopNavProps) {
  const pathname = usePathname() || "/";
  const items =
    variant === "mobile-secondary"
      ? navItems.filter((item) => !coreNavHrefs.has(item.href))
      : navItems;

  if (items.length === 0) {
    return null;
  }

  return (
    <nav
      aria-label={variant === "desktop" ? "Primary navigation" : "Secondary navigation"}
      className="w-full"
    >
      {variant === "mobile-secondary" ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-[0.76rem] font-medium text-[var(--muted)]">
            More:
          </span>
          {items.map((item) => {
            const isActive = isRouteActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-full px-2 py-1.5 font-medium ${
                  isActive ? "text-[var(--text)]" : "text-[var(--muted)]"
                }`}
                aria-current={isActive ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="flex w-full justify-start">
          <div className="inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-[var(--line-soft)] bg-[var(--panel-soft)] p-1">
            {items.map((item) => {
              const isActive = isRouteActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-chip whitespace-nowrap ${isActive ? "nav-chip-active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </nav>
  );
}
