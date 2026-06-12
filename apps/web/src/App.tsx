import { useEffect, useMemo, useState } from "react";
import { Shell } from "./components/Shell";
import { OrderDetailsPage } from "./pages/OrderDetailsPage";
import { StoreRankingPage } from "./pages/StoreRankingPage";
import { StoreSettlementPage } from "./pages/StoreSettlementPage";

function readLocation() {
  return {
    pathname: window.location.pathname === "/" ? "/ranking" : window.location.pathname,
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

  const page =
    location.pathname === "/settlement" ? (
      <StoreSettlementPage searchParams={searchParams} />
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
