import { useEffect, useRef, useState } from 'react';
import { Button } from './Button';
import { FieldInput } from './FormControls';
import { commitBulkAccounts, downloadBulkAccountTemplate, previewBulkAccounts, type BulkAccountPreview } from '../api/client';

export function AccountBulkImport({ onCreated }: { onCreated: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BulkAccountPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [results, setResults] = useState<{ url: string; count: number }[]>([]);
  const resultRef = useRef<string[]>([]);
  useEffect(() => () => { resultRef.current.forEach(url => URL.revokeObjectURL(url)); }, []);
  const upload = async (next: File | null) => {
    setFile(next); setPreview(null); setMessage('');
    if (!next) return;
    setBusy(true);
    try { setPreview((await previewBulkAccounts(next)).data); }
    catch (error) { setMessage(error instanceof Error ? error.message : '校验失败，请检查模板'); }
    finally { setBusy(false); }
  };
  const commit = async () => {
    if (!file || !preview || busy) return;
    setBusy(true); setMessage('');
    try {
      const result = await commitBulkAccounts(file, preview.digest);
      const url = URL.createObjectURL(result); resultRef.current.push(url);
      setResults(current => [...current, { url, count: preview.rows.length }]);
      setMessage(`已创建 ${preview.rows.length} 个账号，请立即下载开通结果，其中包含初始密码。`);
      setPreview(null); setFile(null); onCreated();
    } catch (error) {
      setMessage((error instanceof Error ? error.message : '创建未确认') + '。如网络中断，请先核对账号列表；已创建账号可重置密码。');
    } finally { setBusy(false); }
  };
  return <section className="content-section account-scope-picker">
    <div className="section-title"><div><h2>批量开通账号</h2><p>下载标准表格给人员填写，上传后统一校验和创建。每批最多 200 个账号。</p></div></div>
    <div className="account-scope-actions">
      <Button type="button" onClick={() => void downloadBulkAccountTemplate().catch(error => setMessage(error.message))}>下载账号开通模板</Button>
      <label className="filter-field"><span>上传账号开通表（xlsx）</span><FieldInput type="file" accept=".xlsx" disabled={busy} aria-label="上传账号开通表" onChange={event => { void upload(event.target.files?.[0] ?? null); event.target.value = ''; }} /></label>
    </div>
    {busy && <p role="status">正在处理，请勿重复提交…</p>}
    {preview && <>
      <p>可开通 {preview.rows.length} 个 · 错误 {preview.errors.length} 行。确认前不会创建账号。</p>
      <div className="account-scope-list">
        {preview.errors.map(error => <p key={error.row}>第 {error.row} 行：{error.reason}</p>)}
        {preview.rows.map(row => <p key={row.row}>{row.username} · {row.display_name} · {row.account_type} · {row.scope}</p>)}
      </div>
      <Button type="button" variant="primary" disabled={busy || !!preview.errors.length || !preview.rows.length} onClick={() => void commit()}>确认批量创建 {preview.rows.length} 个账号</Button>
    </>}
    {message && <p role="status">{message}</p>}
    {results.map((result, index) => <a key={result.url} className="ui-button ui-button--primary" href={result.url} download={`账号开通结果-${index + 1}.xlsx`}>下载第 {index + 1} 批开通结果（{result.count} 个账号，含初始密码）</a>)}
    <small>初始密码统一为 123456，登录后请在账号菜单中修改密码。开通结果仅在本页保留，离开前请下载并妥善分发。</small>
  </section>;
}
