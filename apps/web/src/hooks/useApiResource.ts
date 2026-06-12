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
) {
  const [reloadIndex, setReloadIndex] = useState(0);
  const [state, setState] = useState<ApiResourceState<T>>({
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;

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
  }, [...dependencies, reloadIndex]);

  const reload = useCallback(() => {
    setReloadIndex((current) => current + 1);
  }, []);

  return { ...state, reload };
}
