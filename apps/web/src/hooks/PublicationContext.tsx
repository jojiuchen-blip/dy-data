import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import type { DashboardPublication } from "../types/dashboard";

interface PublicationContextValue {
  publication?: DashboardPublication;
  pin: { current: DashboardPublication | undefined };
  refreshIndex: number;
  refreshLatest: () => void;
  claimRecovery: () => boolean;
  recoverLatest: () => boolean;
  finishRecovery: () => void;
  show: (publication: DashboardPublication, onlyIfSame?: boolean) => void;
  analysisActive: boolean;
  setAnalysisActive: (active: boolean) => void;
  notice: string;
  setNotice: (notice: string) => void;
}

const PublicationContext = createContext<PublicationContextValue | null>(null);

/** Scoped to the authenticated account and page; contains no cached business rows. */
export function DashboardPublicationProvider({ children }: { children: ReactNode }) {
  const pin = useRef<DashboardPublication | undefined>(undefined);
  const [publication, setPublication] = useState<DashboardPublication>();
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [notice, setNotice] = useState("");
  const [analysisActive, setAnalysisActive] = useState(false);
  const recoveryUsed = useRef(false);
  const recoveryPending = useRef(false);
  const claimRecovery = useCallback(() => {
    if (recoveryUsed.current) return false;
    recoveryUsed.current = true;
    return true;
  }, []);
  const recoverLatest = useCallback(() => {
    if (!claimRecovery()) return false;
    recoveryPending.current = true;
    setRefreshIndex((value) => value + 1);
    return true;
  }, [claimRecovery]);
  const finishRecovery = useCallback(() => {
    if (recoveryPending.current) {
      recoveryPending.current = false;
      setNotice("原结果版本已过期，已重新读取最新发布结果。");
    }
  }, []);
  const refreshLatest = useCallback(() => {
    setNotice("");
    recoveryPending.current = false;
    recoveryUsed.current = false;
    setRefreshIndex((value) => value + 1);
  }, []);
  const show = useCallback((next: DashboardPublication, onlyIfSame = false) => setPublication((current) => onlyIfSame && current?.id !== next.id ? current : next), []);
  const value = useMemo(() => ({ publication, pin, refreshIndex, refreshLatest, claimRecovery, recoverLatest, finishRecovery, show, notice, setNotice, analysisActive, setAnalysisActive }),
    [publication, refreshIndex, refreshLatest, claimRecovery, recoverLatest, finishRecovery, show, notice, analysisActive]);
  return <PublicationContext.Provider value={value}>{children}</PublicationContext.Provider>;
}

export function useDashboardPublication() {
  const context = useContext(PublicationContext);
  if (!context) throw new Error("DashboardPublicationProvider is required");
  return context;
}
