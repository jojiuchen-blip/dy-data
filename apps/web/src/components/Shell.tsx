import type { ReactNode } from "react";

const navItems = [
  { href: "/", label: "模块首页" },
  { href: "/ranking", label: "门店榜单" },
  { href: "/settlement", label: "单店分账" },
  { href: "/details", label: "数据明细" },
];

interface ShellProps {
  currentPath: string;
  children: ReactNode;
}

export function Shell({ currentPath, children }: ShellProps) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/">
          <img
            aria-hidden="true"
            className="brand__mark"
            src="/business-loop-icon.svg"
            alt=""
          />
          <div>
            <strong>抖音经营数据引擎</strong>
            <span>订单结算中心</span>
          </div>
        </a>
        <nav className="topnav" aria-label="主导航">
          {navItems.map((item) => (
            <a
              aria-current={currentPath === item.href ? "page" : undefined}
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
