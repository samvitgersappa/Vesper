"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

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
  const [open, setOpen] = useState(false);

  return (
    <nav className={`nav${open ? " nav-open" : ""}`}>
      <div className="nav-topline">
        <Link href="/" className="brand" onClick={() => setOpen(false)}>
          Vesper
        </Link>
        <div className="nav-status"><span className="live-dot" />Local-first workspace</div>
        <button className="nav-toggle" aria-label="Toggle navigation" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          <span /><span /><span />
        </button>
      </div>
      <div className="nav-links" onClick={() => setOpen(false)}>
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
