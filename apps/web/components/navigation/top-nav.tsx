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
  const activeItem = items.find((item) => isRouteActive(pathname, item.href));

  if (items.length === 0) {
    return null;
  }

  return (
    <nav
      aria-label={variant === "desktop" ? "Primary navigation" : "Secondary navigation"}
      className="w-full"
    >
      {variant === "mobile-secondary" ? (
        <details className="rounded-[1.2rem] border border-[var(--line-soft)] bg-[var(--panel-soft)]">
          <summary className="collapsible-summary flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="text-[0.64rem] font-semibold uppercase tracking-[0.22em] text-[var(--muted)]">
                More Sections
              </p>
              <p className="mt-1 truncate text-sm font-medium text-[var(--text)]">
                {activeItem?.label ?? "Analytics, Backtests, Risk"}
              </p>
            </div>
            <span className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--line-soft)] bg-[var(--panel)] text-[var(--muted)]">
              +
            </span>
          </summary>
          <div className="flex flex-wrap gap-2 border-t border-[var(--line-soft)] px-3 py-3">
            {items.map((item) => {
              const isActive = isRouteActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-chip whitespace-nowrap px-3 py-2 text-sm ${
                    isActive ? "nav-chip-active" : ""
                  }`}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </details>
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
