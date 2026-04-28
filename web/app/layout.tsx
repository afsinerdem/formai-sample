import "./globals.css";
import type { Metadata } from "next";
import localFont from "next/font/local";
import { SiteFooter, SiteHeader } from "../components/site-chrome";

const displaySans = localFont({
  src: [
    {
      path: "./fonts/Arial-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/Arial-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-display",
});

const bodySans = localFont({
  src: [
    {
      path: "./fonts/Arial-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/Arial-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-body",
});

const spaceMono = localFont({
  src: [
    {
      path: "./fonts/Courier-New-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./fonts/Courier-New-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "FormAI",
  description: "Enterprise form automation add-on with fillable PDF generation, OCR extraction, and local/private deployment options.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${displaySans.variable} ${bodySans.variable} ${spaceMono.variable}`}>
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
