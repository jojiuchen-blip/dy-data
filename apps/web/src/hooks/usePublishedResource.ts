import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { ApiRequestError, type ApiLoadResult } from "../api/client";
import { useDashboardPublication } from "./PublicationContext";

interface PublishedState<T> {
  data?: ApiLoadResult<T>;
  error?: string;
  rawError?: unknown;
  loading: boolean;
  refreshing: boolean;
}

/** Analysis-only reader. A filter never releases the pin; only refresh asks for latest. */
export function usePublishedResource<T>(
  load: (publicationId?: string) => Promise<ApiLoadResult<T>>,
  dependencies: DependencyList,
  options: { enabled?: boolean; publicationId?: string; leader?: boolean; announce?: boolean } = {},
) {
  const { pin, refreshIndex, refreshLatest, show, setNotice, setAnalysisActive } = useDashboardPublication();
  const enabled = options.enabled ?? true;
  const leader = options.leader ?? true;
  const announce = options.announce ?? true;
  const explicitId = options.publicationId;
  const generation = leader ? refreshIndex : 0;
  const completedGeneration = useRef(generation);
  const loadRef = useRef(load);
  loadRef.current = load;
  const [retryIndex, setRetryIndex] = useState(0);
  const [state, setState] = useState<PublishedState<T>>({ loading: enabled, refreshing: false });
  const requestRef = useRef(0);
  const wantedKey = JSON.stringify([dependencies, explicitId, generation, retryIndex, enabled]);
  const [resolvedKey, setResolvedKey] = useState("");
  const queryKey = JSON.stringify([dependencies, explicitId, enabled]);
  const resolvedQuery = useRef("");

  useEffect(() => {
    const request = ++requestRef.current;
    let cancelled = false;
    const latest = completedGeneration.current !== generation;
    if (!enabled) {
      setState({ loading: false, refreshing: false });
      return;
    }
    // Keep an old complete result only when the displayed query is unchanged.
    const sameQuery = resolvedQuery.current === queryKey;
    setState((current) => ({ data: sameQuery ? current.data : undefined, loading: !sameQuery || !current.data, refreshing: sameQuery && Boolean(current.data) }));
    const read = async () => {
      let result: ApiLoadResult<T>;
      const id = latest ? undefined : explicitId ?? pin.current?.id;
      try {
        result = await loadRef.current(id);
      } catch (error) {
        if (cancelled || request !== requestRef.current) return;
        if (!(error instanceof ApiRequestError) || error.status !== 410 || !id) throw error;
        if (!leader) {
          setNotice("原结果版本已过期，正在重新读取完整发布结果。");
          refreshLatest();
          throw error;
        }
        // One explicit recovery, never retry 422/503 or loop on a second 410.
        setNotice("原结果版本已过期，正在重新读取完整发布结果。");
        result = await loadRef.current(undefined);
        if (!cancelled && request === requestRef.current) setNotice("原结果版本已过期，已重新读取最新发布结果。");
      }
      if (cancelled || request !== requestRef.current) return;
      const publication = result.meta.publication;
      if (!result.usingMock && !publication) throw new Error("已发布结果的版本信息缺失，请稍后重试。");
      if (explicitId && publication && publication.id !== explicitId && !latest) {
        throw new Error("结果版本不一致，请刷新后重试。");
      }
      if (publication) {
        // Explicit-ID data reads describe immutable contents as available; keep
        // the matching leader metadata status about the latest background attempt.
        const displayPublication = !leader && pin.current?.id === publication.id
          ? { ...publication, status: pin.current.status, nextRefreshAt: pin.current.nextRefreshAt }
          : publication;
        pin.current = displayPublication;
        show(displayPublication, !announce);
      }
      completedGeneration.current = generation;
      resolvedQuery.current = queryKey;
      setResolvedKey(wantedKey);
      setState({ data: result, loading: false, refreshing: false });
    };
    void read().catch((error: unknown) => {
      if (cancelled || request !== requestRef.current) return;
      const statusMessages: Record<number, string> = {
        401: "登录状态已失效，请重新登录。",
        403: "当前账号没有查看此分析结果的权限。",
        410: "原结果版本已过期，请读取最新结果。",
        422: "筛选条件不正确，请调整后重试。",
        503: "发布结果暂不可用，请稍后重试；后台会继续准备数据。",
      };
      const message = error instanceof ApiRequestError
        ? statusMessages[error.status] ?? "发布结果读取失败，请稍后重试。"
        : error instanceof TypeError ? "网络连接异常，请检查后重试。"
        : "发布结果或版本信息暂不可用，请读取最新结果。";
      setResolvedKey(wantedKey);
      const mayKeepPrevious = sameQuery && !(error instanceof ApiRequestError && [401, 403, 410, 422].includes(error.status));
      setState((current) => ({ data: mayKeepPrevious ? current.data : undefined, error: message, rawError: error, loading: false, refreshing: false }));
    });
    return () => { cancelled = true; };
    // The caller explicitly declares query dependencies; loadRef avoids callback loops.
  }, [wantedKey, queryKey, enabled, explicitId, generation, leader, announce, pin, show, setNotice, refreshLatest]);

  const reload = useCallback(() => {
    if (leader) refreshLatest();
    else setRetryIndex((value) => value + 1);
  }, [leader, refreshLatest]);

  useEffect(() => {
    if (!leader || !enabled) return;
    setAnalysisActive(true);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refreshLatest();
    }, 5 * 60 * 1000);
    return () => { window.clearInterval(timer); setAnalysisActive(false); };
  }, [leader, enabled, refreshLatest, setAnalysisActive]);

  const current = resolvedKey === wantedKey;
  const sameQuery = resolvedQuery.current === queryKey;
  return { ...state, data: current || sameQuery ? state.data : undefined, loading: enabled && ((!current && !sameQuery) || state.loading), reload };
}
