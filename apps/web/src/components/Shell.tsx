import type { ReactNode } from "react";
import { CommissionRulesButton } from "./CommissionRulesButton";

const settlementPaths = new Set(["/ranking", "/settlement", "/details"]);

const primaryNavItems = [
  { href: "/ranking", label: "订单分佣结算中心", section: "settlement" },
  { href: "/clues", label: "线索跟进分配中心", section: "clues" },
];

const settlementNavItems = [
  { href: "/ranking", label: "全国门店榜单" },
  { href: "/settlement", label: "单店分账看板" },
  { href: "/details", label: "月度数据明细" },
];

interface ShellProps {
  currentPath: string;
  children: ReactNode;
}

export function Shell({ currentPath, children }: ShellProps) {
  const inSettlementCenter = settlementPaths.has(currentPath);

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
            <span>订单分佣结算中心</span>
          </div>
        </a>
        <div className="topnav-stack">
          <nav className="topnav topnav--primary" aria-label="主导航">
            {primaryNavItems.map((item) => {
              const active =
                item.section === "settlement"
                  ? inSettlementCenter
                  : currentPath === item.href;
              return (
                <a aria-current={active ? "page" : undefined} href={item.href} key={item.href}>
                  {item.label}
                </a>
              );
            })}
          </nav>
          {inSettlementCenter ? (
            <div className="subnav-row">
              <nav className="topnav topnav--secondary" aria-label="订单分佣结算中心导航">
                {settlementNavItems.map((item) => (
                  <a
                    aria-current={currentPath === item.href ? "page" : undefined}
                    href={item.href}
                    key={item.href}
                  >
                    {item.label}
                  </a>
                ))}
              </nav>
              <CommissionRulesButton />
            </div>
          ) : null}
        </div>
      </header>
      <main className="page-frame">{children}</main>
    </div>
  );
}
