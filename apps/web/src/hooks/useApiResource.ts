import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DependencyList,
} from "react";
import type { ApiLoadResult } from "../api/client";

interface ApiResourceState<T> {
  data?: ApiLoadResult<T>;
  error?: string;
  rawError?: unknown;
  loading: boolean;
  refreshing: boolean;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "未知错误";
}

export function useApiResource<T>(
  load: () => Promise<ApiLoadResult<T>>,
  dependencies: DependencyList,
  options?: { enabled?: boolean },
) {
  const enabled = options?.enabled ?? true;
  const [reloadIndex, setReloadIndex] = useState(0);
  const [state, setState] = useState<ApiResourceState<T>>({
    loading: enabled,
    refreshing: false,
  });
  const requestIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    if (!enabled) {
      setState({
        data: undefined,
        error: undefined,
        rawError: undefined,
        loading: false,
        refreshing: false,
      });
      return () => {
        cancelled = true;
      };
    }

    setState((current) => ({
      data: current.data,
      error: undefined,
      rawError: undefined,
      loading: current.data === undefined,
      refreshing: current.data !== undefined,
    }));

    load()
      .then((data) => {
        if (cancelled) {
          return;
        }
        if (requestId !== requestIdRef.current) {
          return;
        }
        setState({ data, loading: false, refreshing: false });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        if (requestId !== requestIdRef.current) {
          return;
        }
        setState((current) => ({
          data: current.data,
          error: errorMessage(error),
          rawError: error,
          loading: false,
          refreshing: false,
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [...dependencies, reloadIndex, enabled]);

  const reload = useCallback(() => {
    setReloadIndex((current) => current + 1);
  }, []);

  return { ...state, reload };
}
