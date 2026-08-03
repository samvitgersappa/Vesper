"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview", color: "#7aa2ff" },
  { href: "/graph", label: "Intelligence", color: "#b980f7" },
  { href: "/people", label: "Relationships", color: "#ff7a8a" },
  { href: "/journal", label: "Journal", color: "#f6c445" },
  { href: "/finance", label: "Wealth", color: "#3ddc97" },
  { href: "/spending", label: "Spending", color: "#ff6d9c" },
  { href: "/ipo", label: "IPOs", color: "#4fd8e0" },
  { href: "/study", label: "Learning", color: "#5b8cff" },
  { href: "/calendar", label: "Calendar", color: "#a8e05f" },
];

const EXTERNAL_LINKS = [{ href: "/brain/", label: "Brain", color: "#b980f7" }];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="nav">
      <Link href="/" className="brand">
        Vesper
      </Link>
      <div className="nav-links">
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname?.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""}>
              <span className="nav-dot" style={{ background: l.color, color: l.color }} />
              {l.label}
            </Link>
          );
        })}
        {EXTERNAL_LINKS.map((l) => (
          <a
            key={l.href}
            href={l.href}
            className={pathname?.startsWith(l.href) ? "active" : ""}
          >
            <span className="nav-dot" style={{ background: l.color, color: l.color }} />
            {l.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
