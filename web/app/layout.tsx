import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Reconciliation Console",
  description:
    "Autonomous payment reconciliation for Razorpay, bank statements and the internal ledger.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:border focus:border-border focus:bg-surface focus:px-3 focus:py-1.5"
        >
          Skip to content
        </a>

        <header className="sticky top-0 z-30 border-b border-border bg-surface/95 backdrop-blur">
          <div className="mx-auto flex h-11 max-w-[1400px] items-center gap-5 px-4 md:px-6">
            <Link
              href="/"
              className="flex items-baseline gap-2 text-[13px] font-semibold tracking-tight"
            >
              Reconciliation
              <span className="text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                Console
              </span>
            </Link>
            <nav aria-label="Primary" className="flex items-center gap-1">
              <NavLink href="/">Status</NavLink>
              <NavLink href="/batches">Batches</NavLink>
            </nav>
          </div>
        </header>

        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">
          {children}
        </main>

        <footer className="border-t border-border px-4 py-3 md:px-6">
          <p className="mx-auto max-w-[1400px] text-[11px] text-muted-foreground">
            All figures are computed from integer paise. Nothing on this page is rounded
            before display.
          </p>
        </footer>
      </body>
    </html>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-sm px-2 py-1.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {children}
    </Link>
  );
}
