import { type DependencyList } from "react";
import { type ApiLoadResult, type ApiRequestError } from "../api/client";
import { usePublishedResource } from "./usePublishedResource";
import { isPublicationPeriodNotReady, PUBLICATION_PERIOD_NOT_READY_TEXT } from "../utils/apiErrors";

type PublishedView<F, T> = { filters: ApiLoadResult<F> } & (
  { state: "ready"; result: T } | { state: "period-not-ready"; error: ApiRequestError }
);

/** Metadata and analytical rows form one committed view. Candidate filters never
 * become visible or replace the page pin before all matching rows are ready,
 * except an explicit unavailable period commits authorized filters with no rows. */
export function usePublishedView<F, T>(
  loadFilters: (publicationId?: string) => Promise<ApiLoadResult<F>>,
  loadData: (filters: F, publicationId?: string) => Promise<ApiLoadResult<T>>,
  dependencies: DependencyList,
  options: { enabled?: boolean } = {},
) {
  const resource = usePublishedResource<PublishedView<F, T>>(async (publicationId) => {
    // Revalidate current permissions even when immutable source contents stay pinned.
    const filters = await loadFilters(publicationId);
    const publication = filters.meta.publication;
    if (!filters.usingMock && !publication) throw new Error("筛选条件缺少发布版本，请读取最新结果。");
    if (publicationId && publication && publication.id !== publicationId) throw new Error("筛选条件版本不一致，请读取最新结果。");
    let result: ApiLoadResult<T>;
    try {
      result = await loadData(filters.data, publication?.id);
    } catch (error) {
      if (!publication || !isPublicationPeriodNotReady(error)) throw error;
      // The server rejected this period within the exact requested version.
      // Commit its permitted choices and pin, never old or invented zero rows.
      return { ...filters, data: { filters, state: "period-not-ready", error } };
    }
    if (publication && result.meta.publication?.id !== publication.id) {
      throw new Error("筛选条件与分析结果版本不一致，请读取最新结果。");
    }
    return {
      ...result,
      meta: { ...result.meta, publication: publication ?? result.meta.publication },
      data: { filters, state: "ready", result: result.data },
    };
  }, dependencies, options);

  const complete = resource.data;
  const periodError = complete?.data.state === "period-not-ready" ? complete.data.error : undefined;
  return {
    ...resource,
    data: complete?.data.state === "ready" ? { ...complete, data: complete.data.result } : undefined,
    filters: complete?.data.filters,
    error: periodError ? PUBLICATION_PERIOD_NOT_READY_TEXT : resource.error,
    rawError: periodError ?? resource.rawError,
  };
}
