import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Nav } from "@/components/Nav";
import { API_BASE } from "@/lib/api";
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
  title: "crypto-quant-lab",
  description: "업비트 코인 일봉 수집·무결성 검사·백테스트 대시보드",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b border-border bg-panel">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
            <Link href="/" className="font-semibold tracking-tight">
              crypto-quant-lab
            </Link>
            <Nav />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-border text-xs text-muted">
          <div className="mx-auto flex max-w-6xl flex-wrap gap-x-4 gap-y-1 px-4 py-4">
            <span>데이터: 업비트 공개 API (매일 오전 9시대 자동 수집)</span>
            <a className="hover:text-foreground" href={`${API_BASE}/api/docs/`}>
              API 문서
            </a>
            <a className="hover:text-foreground" href="https://github.com/oofy-sotry/crypto-quant-lab">
              GitHub
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
