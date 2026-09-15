import { useMemo, useState } from 'react';
import { Button } from './Button';
import { Dialog } from './Dialog';
import { FieldInput, SelectField } from './FormControls';
import { downloadAccountStoreTemplate, previewAccountStoreImport } from '../api/client';
import type { AccountUpsertPayload, AccountStoreOption, AccountStorePreview } from '../types/dashboard';
import './AccountScopePicker.css';

const levels = ['group', 'service_center', 'district', 'area'];
const fields = ['group_name', 'service_center_name', 'district_name', 'area_name'] as const;
const labels = ['集团', '服务中心', '大区', '区域'];
const scopeFields: Record<string, readonly typeof fields[number][]> = {
  group: ['group_name'], service_center: ['service_center_name'],
  district: ['service_center_name', 'district_name'], area: ['service_center_name', 'district_name', 'area_name'],
};

export function AccountScopePicker({ draft, stores, onChange }: {
  draft: AccountUpsertPayload; stores: AccountStoreOption[]; onChange: (draft: AccountUpsertPayload) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [onlySelected, setOnlySelected] = useState(false);
  const [preview, setPreview] = useState<AccountStorePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const mode = draft.org_scope?.level ?? (draft.store_scope_mode === 'all' ? 'all' : 'store');
  const selected = new Set(draft.store_ids);
  const matches = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    return stores.filter(store => (!onlySelected || draft.store_ids.includes(store.store_id))
      && (!keyword || store.store_id.toLocaleLowerCase().includes(keyword) || store.store_name.toLocaleLowerCase().includes(keyword)));
  }, [stores, query, onlySelected, draft.store_ids]);
  const updateIds = (ids: string[]) => onChange({ ...draft, store_ids: Array.from(new Set(ids)) });
  const importFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setPreview(null); setMessage('');
    try { setPreview((await previewAccountStoreImport(file)).data); }
    catch (error) { setMessage(error instanceof Error ? error.message : '导入失败，请检查文件后重试'); }
    finally { setBusy(false); }
  };
  const activeFields = scopeFields[mode] ?? [];
  const covered = draft.org_scope ? stores.filter(store => activeFields.every(field => draft.org_scope?.[field] && store[field] === draft.org_scope[field])) : [];
  return <div className="account-scope-picker">
    <SelectField label="数据可见范围" value={mode} options={draft.role === 'highest_admin' ? [{ value: 'all', label: '全部门店' }] : [
      ...(draft.role === 'admin' ? [{ value: 'all', label: '全部门店' }, ...levels.map((value, index) => ({ value, label: labels[index] }))] : []),
      { value: 'store', label: '指定门店（可多选）' },
    ]} onChange={value => {
      setPreview(null); setMessage('');
      onChange({ ...draft, store_scope_mode: value === 'all' ? 'all' : 'specified',
        org_scope: levels.includes(value) ? { level: value } : null, store_ids: [] });
    }} />
    {levels.includes(mode) && activeFields.map((field, index) => {
      const parents = activeFields.slice(0, index);
      const label = labels[fields.indexOf(field)];
      const options = Array.from(new Set(stores.filter(store => parents.every(parent => store[parent] === draft.org_scope?.[parent]))
        .map(store => store[field]).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
      return <SelectField key={field} label={label} value={draft.org_scope?.[field] ?? ''}
        options={[{ value: '', label: `请选择${label}` }, ...options.map(value => ({ value, label: value }))]}
        onChange={value => onChange({ ...draft, org_scope: { level: mode, ...Object.fromEntries(parents.map(parent => [parent, draft.org_scope?.[parent] ?? ''])), [field]: value } })} />;
    })}
    {levels.includes(mode) && <p>当前覆盖 {covered.length} 家门店，门店归属调整后自动更新。</p>}
    {levels.includes(mode) && <small>集团单独选择；服务中心、大区、区域不需要填写集团。</small>}
    {mode === 'store' && <>
      <Button type="button" onClick={() => setOpen(true)}>门店权限 · 已选 {draft.store_ids.length} 家</Button>
      <Dialog open={open} title="选择门店权限" onClose={() => setOpen(false)}>
        <div className="account-scope-dialog">
          <label className="filter-field"><span>搜索门店名称或 ID</span><FieldInput autoFocus placeholder="输入名称关键词或部分 ID" value={query} onChange={event => setQuery(event.target.value)} /></label>
          <div className="account-scope-actions">
            <span>匹配 {matches.length} 家 · 已选 {selected.size} 家</span>
            <Button type="button" onClick={() => updateIds([...draft.store_ids, ...matches.map(store => store.store_id)])}>全选搜索结果</Button>
            <Button type="button" onClick={() => updateIds([])}>清空已选</Button>
            <label><input type="checkbox" checked={onlySelected} onChange={event => setOnlySelected(event.target.checked)} />仅看已选</label>
          </div>
          <div className="account-scope-list">
            {matches.map(store => <label className="account-scope-row" key={store.store_id}>
              <input type="checkbox" checked={selected.has(store.store_id)} onChange={event => updateIds(event.target.checked ? [...draft.store_ids, store.store_id] : draft.store_ids.filter(id => id !== store.store_id))} />
              <span><strong>{store.store_name || '未命名门店'}</strong><small>{store.store_id}</small><small>{fields.map(field => store[field]).filter(Boolean).join(' / ')}</small></span>
            </label>)}
            {!matches.length && <p>没有符合条件的门店，请更换关键词。</p>}
          </div>
          <Button type="button" variant="primary" onClick={() => setOpen(false)}>完成选择（{selected.size} 家）</Button>
        </div>
      </Dialog>
      <div className="account-scope-actions">
        <Button type="button" disabled={busy} onClick={() => { void downloadAccountStoreTemplate().catch(error => setMessage(error.message)); }}>下载门店导入模板</Button>
        <label className="filter-field"><span>批量导入门店（Excel / CSV）</span><FieldInput type="file" aria-label="批量导入门店" disabled={busy} accept=".xlsx,.csv,.txt" onChange={event => { void importFile(event.target.files?.[0]); event.target.value = ''; }} /></label>
      </div>
      <small>模板含填写说明和可选门店名单。门店 ID 使用文本格式；导入后需预览并保存账号。</small>
      {busy && <p role="status">正在校验门店名单…</p>}
      {preview && <div className="account-scope-preview">
        <p>匹配 {preview.store_ids.length} 家 · 去重 {preview.duplicate_count} 行 · 错误 {preview.errors.length} 行</p>
        <div className="account-scope-list">
          {preview.errors.map(error => <p key={error.row}>第 {error.row} 行 · {error.store_id || '空 ID'}：{error.reason}</p>)}
          {preview.stores.map(store => <p key={store.store_id}>{store.store_name}（{store.store_id}）</p>)}
        </div>
        <Button type="button" disabled={!preview.store_ids.length || !!preview.errors.length} onClick={() => {
          updateIds([...draft.store_ids, ...preview.store_ids]); setPreview(null); setMessage('已加入当前选择，请保存账号。');
        }}>确认加入已选门店</Button>
        {!!preview.errors.length && <p>请修正错误行后重新上传，本次尚未应用。</p>}
      </div>}
    </>}
    {message && <p role="status">{message}</p>}
    <small>线索中心和结算中心使用此范围；三个打榜指标始终可查看全量排名。</small>
  </div>;
}
