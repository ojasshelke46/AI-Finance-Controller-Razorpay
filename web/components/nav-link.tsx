"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * A primary nav item that shows whether you are already on it.
 *
 * Without this the header had three clickable things and two
 * destinations — the wordmark and "Status" both went to "/" — and
 * nothing marked the current section, so clicking "Status" from the
 * status page looked like a dead link rather than a no-op. Marking the
 * current page is what makes the difference legible.
 */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  // "/batches/<id>" is still the Batches section; "/" only matches itself.
  const active = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-sm px-2 py-1.5 text-[12.5px]",
        active
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}
