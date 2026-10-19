import { useEffect, useRef, type DependencyList } from "react";
import type { ApiLoadResult } from "../api/client";
import { usePublishedResource } from "./usePublishedResource";

/** Metadata and analytical rows form one committed view. Candidate filters never
 * become visible or replace the page pin before all matching rows are ready. */
export function usePublishedView<F, T>(
  loadFilters: (publicationId?: string) => Promise<ApiLoadResult<F>>,
  loadData: (filters: F, publicationId?: string) => Promise<ApiLoadResult<T>>,
  dependencies: DependencyList,
  options: { enabled?: boolean } = {},
) {
  const committedFilters = useRef<ApiLoadResult<F> | undefined>(undefined);
  const resource = usePublishedResource(async (publicationId) => {
    // Reuse only metadata that was committed with a complete page, never a
    // failed candidate. Undefined ID means an explicit latest refresh.
    const filters = publicationId && committedFilters.current?.meta.publication?.id === publicationId
      ? committedFilters.current
      : await loadFilters(publicationId);
    const publication = filters.meta.publication;
    const result = await loadData(filters.data, publication?.id);
    if (publication && result.meta.publication?.id !== publication.id) {
      throw new Error("筛选条件与分析结果版本不一致，请读取最新结果。");
    }
    return {
      ...result,
      meta: { ...result.meta, publication: publication ?? result.meta.publication },
      data: { filters, result: result.data },
    };
  }, dependencies, options);

  const complete = resource.data;
  useEffect(() => {
    if (complete) committedFilters.current = complete.data.filters;
  }, [complete]);

  return {
    ...resource,
    data: complete ? { ...complete, data: complete.data.result } : undefined,
    filters: complete?.data.filters,
  };
}
