import type { ReactNode } from "react";

const navItems = [
  { href: "/ranking", label: "全国门店榜单" },
  { href: "/settlement", label: "单店分账看板" },
  { href: "/details", label: "月度数据明细" },
];

interface ShellProps {
  currentPath: string;
  children: ReactNode;
}

export function Shell({ currentPath, children }: ShellProps) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img
            aria-hidden="true"
            className="brand__mark"
            src="/business-loop-icon.svg"
            alt=""
          />
          <div>
            <strong>抖音经营中枢</strong>
            <span>销售洞察 · 分账核验</span>
          </div>
        </div>
        <nav className="topnav" aria-label="主导航">
          {navItems.map((item) => (
            <a
              aria-current={
                currentPath === item.href ||
                (currentPath === "/" && item.href === "/ranking")
                  ? "page"
                  : undefined
              }
              href={item.href}
              key={item.href}
            >
              {item.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="page-frame">{children}</main>
    </div>
  );
}
