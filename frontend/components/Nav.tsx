"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "홈", match: (p: string) => p === "/" },
  { href: "/assets/KRW-BTC", label: "가격 차트", match: (p: string) => p.startsWith("/assets") },
  { href: "/backtest", label: "백테스트", match: (p: string) => p.startsWith("/backtest") },
  { href: "/integrity", label: "데이터 품질", match: (p: string) => p.startsWith("/integrity") },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 text-sm">
      {LINKS.map(({ href, label, match }) => {
        const active = match(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 transition-colors ${
              active ? "bg-accent/10 font-semibold text-accent" : "text-muted hover:text-foreground"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
