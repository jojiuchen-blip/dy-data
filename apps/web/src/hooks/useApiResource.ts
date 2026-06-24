import { useCallback, useEffect, useState, type DependencyList } from "react";
import type { ApiLoadResult } from "../api/client";

interface ApiResourceState<T> {
  data?: ApiLoadResult<T>;
  error?: string;
  loading: boolean;
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
  });

  useEffect(() => {
    let cancelled = false;

    if (!enabled) {
      setState((current) => ({
        data: current.data,
        error: undefined,
        loading: false,
      }));
      return () => {
        cancelled = true;
      };
    }

    setState((current) => ({
      ...current,
      error: undefined,
      loading: true,
    }));

    load()
      .then((data) => {
        if (!cancelled) {
          setState({ data, loading: false });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState((current) => ({
            ...current,
            error: errorMessage(error),
            loading: false,
          }));
        }
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
