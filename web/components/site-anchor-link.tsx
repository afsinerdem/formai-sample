"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

const HEADER_OFFSET = 96;

function scrollToHash(hash: string) {
  const target = document.getElementById(hash);
  if (!target) {
    return;
  }

  const top = target.getBoundingClientRect().top + window.scrollY - HEADER_OFFSET;
  window.history.replaceState(null, "", `/#${hash}`);
  window.scrollTo({
    top: Math.max(top, 0),
    behavior: "smooth",
  });
}

type Props = {
  href: string;
  children: ReactNode;
  className?: string;
  onNavigate?: () => void;
};

export function SiteAnchorLink({ href, children, className, onNavigate }: Props) {
  const pathname = usePathname();
  const isHashLink = href.startsWith("/#");

  if (!isHashLink) {
    return (
      <Link
        className={className}
        href={href}
        onClick={() => {
          onNavigate?.();
        }}
      >
        {children}
      </Link>
    );
  }

  const hash = href.slice(2);

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onNavigate?.();
    if (pathname !== "/") {
      return;
    }

    event.preventDefault();
    scrollToHash(hash);
  };

  return (
    <a className={className} href={href} onClick={handleClick}>
      {children}
    </a>
  );
}
