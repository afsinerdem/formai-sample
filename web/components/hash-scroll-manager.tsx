"use client";

import { useEffect } from "react";

const HEADER_OFFSET = 96;

function scrollToHash(hash: string, behavior: ScrollBehavior = "smooth") {
  const target = document.getElementById(hash);
  if (!target) {
    return;
  }

  const top = target.getBoundingClientRect().top + window.scrollY - HEADER_OFFSET;
  window.scrollTo({
    top: Math.max(top, 0),
    behavior,
  });
}

export function HashScrollManager() {
  useEffect(() => {
    const applyHashScroll = (behavior: ScrollBehavior) => {
      const hash = window.location.hash.replace(/^#/, "");
      if (!hash) {
        return;
      }
      window.requestAnimationFrame(() => scrollToHash(hash, behavior));
    };

    applyHashScroll("auto");

    const onHashChange = () => applyHashScroll("smooth");
    window.addEventListener("hashchange", onHashChange);

    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  return null;
}
