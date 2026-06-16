import { useEffect, useMemo, useState } from "react";
import { AdminHomePage } from "./pages/AdminHomePage";
import { AdminClueRulePage } from "./pages/AdminClueRulePage";
import { Shell } from "./components/Shell";
import { AdminSkuRulesPage } from "./pages/AdminSkuRulesPage";
import { AdminSyncPage } from "./pages/AdminSyncPage";
import { ClueCenterPage } from "./pages/ClueCenterPage";
import { HomePage } from "./pages/HomePage";
import { OrderDetailsPage } from "./pages/OrderDetailsPage";
import { StoreRankingPage } from "./pages/StoreRankingPage";
import { StoreSettlementPage } from "./pages/StoreSettlementPage";

function readLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

export function App() {
  const [location, setLocation] = useState(readLocation);

  useEffect(() => {
    const syncLocation = () => setLocation(readLocation());

    const handleClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) {
        return;
      }

      const target = event.target as Element | null;
      const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor) {
        return;
      }

      const url = new URL(anchor.href);
      if (url.origin !== window.location.origin) {
        return;
      }

      event.preventDefault();
      window.history.pushState(null, "", `${url.pathname}${url.search}${url.hash}`);
      syncLocation();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    window.addEventListener("popstate", syncLocation);
    document.addEventListener("click", handleClick);
    return () => {
      window.removeEventListener("popstate", syncLocation);
      document.removeEventListener("click", handleClick);
    };
  }, []);

  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );

  if (location.pathname === "/admin") {
    return <AdminHomePage />;
  }

  if (location.pathname === "/rule-admin" || location.pathname === "/admin/rules") {
    return <AdminSkuRulesPage />;
  }

  if (location.pathname === "/sync-admin" || location.pathname === "/admin/sync") {
    return <AdminSyncPage />;
  }

  if (location.pathname === "/admin/clues/rules") {
    return <AdminClueRulePage />;
  }

  if (location.pathname === "/") {
    return <HomePage />;
  }

  const page =
    location.pathname === "/settlement" ? (
      <StoreSettlementPage searchParams={searchParams} />
    ) : location.pathname === "/clues" ? (
      <ClueCenterPage searchParams={searchParams} />
    ) : location.pathname === "/details" ? (
      <OrderDetailsPage searchParams={searchParams} />
    ) : (
      <StoreRankingPage searchParams={searchParams} />
    );

  return (
    <Shell currentPath={location.pathname}>
      {page}
    </Shell>
  );
}
