import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { NavLink } from "@/components/nav-link";
import { SectionTransition } from "@/components/section-transition";

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
          <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-5 px-4 md:px-6">
            {/* The wordmark is identity, not navigation. It used to link
             *  to "/", which is also where "Status" goes — three
             *  clickable things, two destinations, and no indication of
             *  the current section, so every one of them looked like it
             *  did nothing. Navigation lives in the nav; Status is the
             *  home route and says so by being marked current. */}
            <span className="flex items-center gap-2.5">
              {/* The Razorpay logo, as a credit for the integration this
               *  console reconciles against — one instance, nav only.
               *
               *  The full lockup rather than the mark alone. In this
               *  asset the mark is a blue arrow PLUS a white
               *  parallelogram, and a previous crop of "just the mark"
               *  silently lost the white half, because compositing the
               *  source on white made it invisible to look at. Using the
               *  lockup whole avoids re-deriving a mark from an asset
               *  whose shape is not visible against every background.
               *
               *  Rendered through a CSS mask filled with currentColor
               *  rather than as a plain <img>, so it takes
               *  muted-foreground like every other non-severity element
               *  in this header. brand.md principle 2 reserves all
               *  chromatic colour for severity; dropping a brand-blue
               *  logo into the nav would put a saturated blue on the
               *  same screen as the critical and warn tokens and give
               *  the eye something to read as a status that is not one.
               *  The mask also solves this asset's white wordmark, which
               *  would otherwise be invisible in light mode.
               *
               *  role="img" + aria-label because this is meaningful
               *  content, not decoration; 1693x360 source at 22px tall
               *  is a ~16x downscale, so it stays crisp on retina. */}
              <span
                role="img"
                aria-label="Razorpay"
                className="h-[22px] w-[104px] shrink-0 text-muted-foreground"
                style={{
                  backgroundColor: "currentColor",
                  maskImage: "url(/razorpay-logo.png)",
                  WebkitMaskImage: "url(/razorpay-logo.png)",
                  maskSize: "contain",
                  WebkitMaskSize: "contain",
                  maskRepeat: "no-repeat",
                  WebkitMaskRepeat: "no-repeat",
                  maskPosition: "center",
                  WebkitMaskPosition: "center",
                }}
              />
              <span className="flex items-baseline gap-2 text-[13px] font-semibold tracking-tight">
                Reconciliation
                <span className="text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                  Console
                </span>
              </span>
            </span>
            <nav aria-label="Primary" className="flex items-center gap-1">
              <NavLink href="/">Status</NavLink>
              <NavLink href="/batches">Batches</NavLink>
            </nav>
          </div>
        </header>

        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">
          <SectionTransition>{children}</SectionTransition>
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
