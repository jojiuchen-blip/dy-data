import { useEffect, useRef, useState } from "react";
import { ApiRequestError, resolveClueStores } from "../api/client";
import type { ClueSelectedStore, ClueStoreResolution } from "../types/clueFilters";
import { userFacingError } from "../utils/userFacingError";
import { Button } from "./Button";
import { FilterChip } from "./Chips";
import { FieldTextarea } from "./FormControls";
import { Dialog } from "./Dialog";
import { SearchableStoreSelect } from "./SearchableStoreSelect";
import "./ClueStoreFilter.css";

interface Props {
  selection: ClueSelectedStore[] | null;
  options: ClueSelectedStore[];
  loading: boolean;
  scopeKey: string;
  resetKey: number;
  onOpen: () => void;
  onSearch: (query: string) => void;
  onChange: (stores: ClueSelectedStore[] | null) => void;
}

/** Name selection and exact ID paste share one visible, bounded store set. */
export function ClueStoreFilter({ selection, options, loading, scopeKey, resetKey, onOpen, onSearch, onChange }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ClueStoreResolution | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const requestVersion = useRef(0);
  useEffect(() => {
    requestVersion.current += 1;
    setText(""); setResult(null); setError(""); setBusy(false);
  }, [scopeKey, resetKey]);
  useEffect(() => {
    if (selection === null) {
      requestVersion.current += 1;
      setText(""); setResult(null); setError(""); setBusy(false);
    }
  }, [scopeKey, selection === null]);
  useEffect(() => () => { requestVersion.current += 1; }, []);
  const merge = (incoming: ClueSelectedStore[]) => {
    const merged = new Map((selection ?? []).map(store => [store.store_id, store]));
    incoming.forEach(store => {
      const previous = merged.get(store.store_id);
      const matches = new Map((previous?.matches ?? []).map(match => [match.identifier, match]));
      (store.matches ?? []).forEach(match => {
        matches.set(match.identifier, { identifier: match.identifier,
          sources: [...new Set([...(matches.get(match.identifier)?.sources ?? []), ...match.sources])] });
      });
      merged.set(store.store_id, { ...store, matches: [...matches.values()] });
    });
    if (merged.size > 1000) { setError("最多选择 1000 家门店；本次未应用，请分批筛选。"); return false; }
    onChange([...merged.values()]);
    return true;
  };
  const apply = async () => {
    if (text.length > 128000) { setError("粘贴内容最多 128000 个字符，请分批筛选。"); return; }
    const version = ++requestVersion.current;
    setBusy(true); setError("");
    try {
      const response = await resolveClueStores(text);
      if (version !== requestVersion.current) return;
      if (merge(response.data.stores)) { setResult(response.data); setPasteOpen(false); }
    } catch (failure) {
      if (version === requestVersion.current) setError(failure instanceof ApiRequestError && failure.code === "CLUE_STORE_FILTER_LIMIT"
        ? failure.message : userFacingError(failure, "ID 解析失败，请检查数量和长度后重试。"));
    } finally { if (version === requestVersion.current) setBusy(false); }
  };
  return <div className="clue-store-filter">
    <SearchableStoreSelect allowEmpty={false} options={options.map(store => ({ value: store.store_id, label: store.store_name }))}
      value="" placeholder="搜索门店名称并多选" loading={loading} disabled={busy}
      onOpen={onOpen} onSearch={onSearch} onChange={id => {
        const store = options.find(option => option.store_id === id);
        if (store) { setError(""); merge([store]); }
      }} />
    <div className="clue-store-filter__commands">
      <Button type="button" size="sm" variant="text" onClick={() => setPasteOpen(!pasteOpen)} aria-expanded={pasteOpen}>批量粘贴 ID</Button>
      {selection !== null ? <Button type="button" size="sm" variant="text" disabled={busy} onClick={() => onChange(null)}>清空门店筛选</Button> : null}
    </div>
    <Dialog open={pasteOpen} title="批量筛选门店" closeLabel="关闭批量筛选" closeDisabled={busy} onClose={() => setPasteOpen(false)}>
      <div className="clue-store-filter__paste">
      <label htmlFor="clue-store-identifiers">所属账户 ID / 门店位置编号（POI ID）</label>
      <FieldTextarea id="clue-store-identifiers" rows={4} value={text} disabled={busy}
        onChange={event => setText(event.target.value)} placeholder="可混合粘贴，支持空格、分号、斜杠、换行及 Tab" />
      <p>最多 1000 个不同 ID，每个最多 128 字符；精确匹配后加入当前名称选择。</p>
      <Button type="button" size="sm" loading={busy} disabled={busy || !text.trim()} onClick={apply}>解析并加入筛选</Button>
      {error ? <p role="alert">{error}</p> : null}
      </div>
    </Dialog>
    {error && !pasteOpen ? <p role="alert">{error}</p> : null}
    {result ? <div role="status">
      <p>解析 {result.input_count} 项 · 不同 ID {result.unique_count} 个 · 重复 {result.duplicate_count} 项 · 匹配 {result.matched_identifier_count} 个 ID / {result.matched_store_count} 家门店</p>
      {result.unmatched_identifiers.length ? <details><summary>未匹配或无权限：{result.unmatched_identifiers.length} 个</summary><p className="clue-store-filter__unmatched">{result.unmatched_identifiers.join("；")}</p></details> : null}
    </div> : null}
    {selection !== null ? <div className="clue-store-filter__selected" aria-label="已选门店">
      <span>已选 {selection.length} 家{selection.length === 0 ? "，当前结果为零；清空筛选可恢复查询" : ""}</span>
      {selection.map(store => <FilterChip key={store.store_id} disabled={busy}
        aria-label={`移除门店 ${store.store_name}`}
        title={store.matches?.map(match => `${match.sources.map(source => source === "account" ? "账户" : "POI").join("/")} ${match.identifier}`).join("；") || store.store_id}
        onClick={() => onChange(selection.filter(item => item.store_id !== store.store_id))}>
        {store.store_name} · {store.matches?.flatMap(match => match.sources).filter((source, index, all) => all.indexOf(source) === index).map(source => source === "account" ? "账户 ID" : "POI ID").join(" / ") || "名称选择"}
      </FilterChip>)}
    </div> : null}
  </div>;
}
