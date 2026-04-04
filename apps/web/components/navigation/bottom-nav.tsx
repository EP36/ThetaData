"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type BottomNavItem = {
  href: string;
  label: string;
  icon: ({ active }: { active: boolean }) => JSX.Element;
};

function isRouteActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function DashboardIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`h-5 w-5 ${active ? "scale-[1.02]" : ""}`}
      aria-hidden="true"
    >
      <path d="M4 13.5h6.5V20H4z" />
      <path d="M13.5 4H20v7.5h-6.5z" />
      <path d="M13.5 13.5H20V20h-6.5z" />
      <path d="M4 4h6.5v6.5H4z" />
    </svg>
  );
}

function TradesIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`h-5 w-5 ${active ? "scale-[1.02]" : ""}`}
      aria-hidden="true"
    >
      <path d="M4 18h4l2.5-5 3 6 2.5-4H20" />
      <path d="M5 7h14" />
      <path d="M5 12h5" />
    </svg>
  );
}

function StrategiesIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`h-5 w-5 ${active ? "scale-[1.02]" : ""}`}
      aria-hidden="true"
    >
      <path d="M6 8.5h12" />
      <path d="M6 15.5h7" />
      <path d="M16.5 14v4.5" />
      <path d="M9 6v5" />
      <circle cx="9" cy="13" r="2" />
      <circle cx="16.5" cy="11" r="2" />
    </svg>
  );
}

function SettingsIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`h-5 w-5 ${active ? "scale-[1.02]" : ""}`}
      aria-hidden="true"
    >
      <path d="M12 7.5A4.5 4.5 0 1 1 7.5 12 4.5 4.5 0 0 1 12 7.5Z" />
      <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a1.3 1.3 0 0 1 0 1.8l-1.7 1.7a1.3 1.3 0 0 1-1.8 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V21a1.3 1.3 0 0 1-1.3 1.3h-2.4A1.3 1.3 0 0 1 9.4 21v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a1.3 1.3 0 0 1-1.8 0L4.1 18.5a1.3 1.3 0 0 1 0-1.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H3.3A1.3 1.3 0 0 1 2 13.6v-2.4A1.3 1.3 0 0 1 3.3 9.9h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a1.3 1.3 0 0 1 0-1.8l1.7-1.7a1.3 1.3 0 0 1 1.8 0l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V3.8A1.3 1.3 0 0 1 10.7 2.5h2.4a1.3 1.3 0 0 1 1.3 1.3V4a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a1.3 1.3 0 0 1 1.8 0l1.7 1.7a1.3 1.3 0 0 1 0 1.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6h.2A1.3 1.3 0 0 1 22 11.2v2.4a1.3 1.3 0 0 1-1.3 1.3h-.2a1 1 0 0 0-.9.6Z" />
    </svg>
  );
}

const navItems: BottomNavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: DashboardIcon },
  { href: "/trades", label: "Trades", icon: TradesIcon },
  { href: "/strategies", label: "Strategies", icon: StrategiesIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon }
];

export function BottomNav() {
  const pathname = usePathname() || "/";

  return (
    <nav aria-label="Primary mobile navigation" className="fixed inset-x-0 bottom-3 z-50 px-3 md:hidden">
      <div className="mx-auto max-w-[34rem]">
        <div className="bottom-nav-shell">
          {navItems.map((item) => {
            const active = isRouteActive(pathname, item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`bottom-nav-link ${active ? "bottom-nav-link-active" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                <span className="bottom-nav-icon">
                  <Icon active={active} />
                </span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
