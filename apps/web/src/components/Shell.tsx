import type { ReactNode } from "react";

const navItems = [
  { href: "/ranking", label: "全国门店榜单" },
  { href: "/settlement", label: "单店分账看板" },
  { href: "/details", label: "月度数据明细" },
];

interface ShellProps {
  currentPath: string;
  children: ReactNode;
  onLogout: () => void;
  username: string;
}

export function Shell({ currentPath, children, onLogout, username }: ShellProps) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark">DY</span>
          <div>
            <strong>抖音订单分账数据看板</strong>
            <span>经销商集团经营复核</span>
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
        <div className="topbar-user">
          <span>{username}</span>
          <button onClick={onLogout} type="button">
            退出
          </button>
        </div>
      </header>
      <main className="page-frame">{children}</main>
    </div>
  );
}
