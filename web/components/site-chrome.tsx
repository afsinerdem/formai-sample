"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { SiteAnchorLink } from "./site-anchor-link";

const navItems = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#before-after", label: "Before & after" },
  { href: "/#privacy", label: "Privacy" },
  { href: "/#faq", label: "FAQ" },
  { href: "/workbench", label: "Workbench" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link className="brand-lockup" href="/">
          <span className="brand-mark">F</span>
          <span>
            <strong>FormAI</strong>
            <small>AI form workflows</small>
          </span>
        </Link>
        <button
          type="button"
          className={menuOpen ? "site-menu-toggle site-menu-toggle-open" : "site-menu-toggle"}
          aria-expanded={menuOpen}
          aria-label="Toggle navigation"
          onClick={() => setMenuOpen((current) => !current)}
        >
          <span />
          <span />
        </button>
        <div className={menuOpen ? "site-menu site-menu-open" : "site-menu"}>
          <nav className="site-nav" aria-label="Primary">
            {navItems.map((item) => (
              <SiteAnchorLink key={item.href} href={item.href} onNavigate={() => setMenuOpen(false)}>
                {item.label}
              </SiteAnchorLink>
            ))}
          </nav>
          <div className="header-actions site-header-actions">
            <Link className="button-ghost" href="/workbench" onClick={() => setMenuOpen(false)}>
              Open Workbench
            </Link>
            <Link className="button-primary" href="/demo" onClick={() => setMenuOpen(false)}>
              Book Demo
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="footer-brand footer-brand-minimal">
          <span className="brand-mark">F</span>
          <div>
            <strong>FormAI</strong>
            <p>Cleaner form intake for teams that want a calmer workflow from blank form to final output.</p>
          </div>
        </div>
        <div className="footer-closing">
          <span className="footer-kicker">Built by Octolabs</span>
          <p>FormAI is an Octolabs product.</p>
          <small>Cloud or local, depending on how your team wants to work.</small>
        </div>
      </div>
      <div className="site-footer-bottom">
        <p>© 2026 FormAI by Octolabs</p>
        <div className="footer-inline-actions">
          <Link href="/demo">Book Demo</Link>
          <span aria-hidden="true">·</span>
          <SiteAnchorLink href="/workbench">Open Workbench</SiteAnchorLink>
        </div>
      </div>
    </footer>
  );
}
