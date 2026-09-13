import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Footer } from "@/components/Footer";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "IndicPass",
  description: "Indic-aware password strength estimator — a research interface over the IndicPass engine.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="border-b bg-surface">
          <div className="mx-auto flex w-full max-w-4xl items-baseline gap-3 px-4 py-5 sm:px-6">
            <h1 className="text-xl font-semibold tracking-tight">IndicPass</h1>
            <p className="text-sm text-muted">Indic-Aware Password Strength Estimator</p>
          </div>
        </header>
        {children}
        <Footer />
      </body>
    </html>
  );
}
