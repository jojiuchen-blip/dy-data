import { useEffect, useState } from "react";
import {
  clueRoutingRequestError, fetchClueRoutingGrants, fetchSharedClueRoutingRule,
  saveClueRoutingGrants, saveSharedClueRoutingRule,
  type ClueRoutingGrants, type ClueRoutingProduct, type ClueRoutingRuleSnapshot,
  type ClueRoutingRuleWrite, type SharedClueRoutingRuleResult,
} from "../api/clueRouting";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { CheckboxField, FieldInput } from "./FormControls";
import {
  ClueRoutingRuleEditor, ClueRoutingRuleSummary,
  createClueRoutingRuleDraft, readClueRoutingRuleDraft,
} from "./ClueRoutingRuleEditor";

export function ClueRoutingGrantsDialog({ product, onClose }: {
  product: ClueRoutingProduct | null;
  onClose: () => void;
}) {
  const [grants, setGrants] = useState<ClueRoutingGrants | null>(null);
  const [userIds, setUserIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!product) return;
    let current = true;
    setBusy(true); setError(""); setNotice(""); setGrants(null); setQuery("");
    fetchClueRoutingGrants(product.product_id).then((data) => {
      if (current) { setGrants(data); setUserIds(data.user_ids); }
    }).catch((failure) => {
      if (current) setError(clueRoutingRequestError(failure, "商品授权暂时无法读取。"));
    }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [product?.product_id, reload]);
  const save = async () => {
    if (!product || !grants || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await saveClueRoutingGrants(product.product_id, userIds);
      setNotice("商品负责人授权已保存。");
      try {
        const updated = await fetchClueRoutingGrants(product.product_id);
        setGrants(updated); setUserIds(updated.user_ids);
      } catch (failure) {
        setError(clueRoutingRequestError(failure, "授权已保存，最新结果暂时无法读取，请重新打开核对。"));
      }
    } catch (failure) { setError(clueRoutingRequestError(failure, "授权未保存，请重试。")); }
    finally { setBusy(false); }
  };
  const users = [...(grants?.users ?? [])];
  for (const userId of grants?.user_ids ?? []) {
    if (!users.some((user) => user.user_id === userId)) users.push({ user_id: userId, username: userId, display_name: "已授权账号" });
  }
  const visibleUsers = users.filter((user) => `${user.display_name ?? ""} ${user.username}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <Dialog
    actions={<><Button disabled={busy} onClick={onClose}>关闭</Button><Button disabled={busy || !grants} loading={busy && Boolean(grants)} onClick={() => void save()} variant="primary">保存商品授权</Button></>}
    closeDisabled={busy}
    description={product ? `${product.product_name} · ${product.product_id}。所选账号仅能管理本商品，授权入口由服务端生效。` : undefined}
    onClose={onClose} open={Boolean(product)} panelClassName="clue-routing-grants-dialog" title="管理商品负责人"
  >
    {error ? <p className="admin-error" role="alert">{error}</p> : null}
    {notice ? <p className="resource-notice" role="status">{notice}</p> : null}
    {busy && !grants ? <p role="status">正在读取可授权账号...</p> : null}
    {!busy && !grants ? <Button onClick={() => setReload((value) => value + 1)}>重新读取授权</Button> : null}
    {grants ? <>
      <label className="filter-field"><span>查找账号</span><FieldInput disabled={busy} onChange={(event) => setQuery(event.target.value)} placeholder="姓名或用户名" type="search" value={query} /></label>
      <p className="admin-muted">已选 {userIds.length} 个账号。取消全部后，该商品仅由全国范围管理员管理。</p>
      <div className="clue-routing-grants-list">
        {visibleUsers.map((user) => <CheckboxField
          checked={userIds.includes(user.user_id)} disabled={busy} key={user.user_id}
          label={`${user.display_name || user.username}（${user.username}）`}
          onChange={(event) => setUserIds((current) => event.target.checked ? [...new Set([...current, user.user_id])] : current.filter((id) => id !== user.user_id))}
        />)}
        {!visibleUsers.length ? <p>没有匹配的可授权账号。</p> : null}
      </div>
    </> : null}
  </Dialog>;
}

export function SharedClueRoutingRuleDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [snapshot, setSnapshot] = useState<ClueRoutingRuleSnapshot | null>(null);
  const [draft, setDraft] = useState(() => createClueRoutingRuleDraft(undefined, true));
  const [preview, setPreview] = useState<SharedClueRoutingRuleResult | null>(null);
  const [confirmedRules, setConfirmedRules] = useState<ClueRoutingRuleWrite | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setBusy(true); setError(""); setNotice(""); setPreview(null); setSnapshot(null); setConfirmedRules(null);
    fetchSharedClueRoutingRule().then((data) => {
      if (current) { setSnapshot(data); setDraft(createClueRoutingRuleDraft(data, true)); }
    }).catch((failure) => { if (current) setError(clueRoutingRequestError(failure, "共享规则暂时无法读取。")); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [open, reload]);
  const submit = async (isPreview: boolean) => {
    const parsed = isPreview ? readClueRoutingRuleDraft(draft) : { rules: confirmedRules, error: "" };
    if (parsed.error || !parsed.rules) { setError(parsed.error || "请先预览共享规则。"); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await saveSharedClueRoutingRule(parsed.rules, isPreview);
      if (isPreview) { setPreview(data); setConfirmedRules(parsed.rules); }
      else {
        setPreview(null); setConfirmedRules(null); setSnapshot(data.after);
        setDraft(createClueRoutingRuleDraft(data.after, true));
        setNotice("共享基座已发布。之后首次创建的商品独立版本采用新基座，已有商品和线索版本保持原绑定。");
        try { setSnapshot(await fetchSharedClueRoutingRule()); }
        catch (failure) { setError(clueRoutingRequestError(failure, "发布已完成，最新版本暂时无法读取，请重新打开核对。")); }
      }
    } catch (failure) { setError(clueRoutingRequestError(failure, "共享规则操作未完成，请重试。")); }
    finally { setBusy(false); }
  };
  return <Dialog
    actions={<><Button disabled={busy} onClick={preview ? () => { setPreview(null); setConfirmedRules(null); setError(""); } : onClose}>{preview ? "返回修改" : "关闭"}</Button>
      <Button disabled={busy || !snapshot?.can_manage} loading={busy && Boolean(snapshot)} onClick={() => void submit(!preview)} variant="primary">{preview ? "确认发布共享基座" : "校验并预览共享基座"}</Button></>}
    closeDisabled={busy} description="精诚养车项目组维护。第 0、1 轮采用 10 公里，第 2 轮同城兜底；发布共享基座不会开启商品流转。"
    onClose={onClose} open={open} panelClassName="clue-routing-dialog" title="精诚养车共享规则基座"
  >
    {error ? <p className="admin-error" role="alert">{error}</p> : null}
    {notice ? <p className="resource-notice" role="status">{notice}</p> : null}
    {busy && !snapshot ? <p role="status">正在加载共享规则...</p> : null}
    {!busy && !snapshot ? <Button onClick={() => setReload((value) => value + 1)}>重新读取共享规则</Button> : null}
    {snapshot ? <>
      <p className="admin-muted">当前基座版本：{snapshot.rule_version_id ?? "尚未发布，当前显示一期默认规则"}</p>
      {preview ? <div className="clue-routing-compare">
        <section><h3>发布前</h3><ClueRoutingRuleSummary snapshot={preview.before} /></section>
        <section><h3>发布后</h3><ClueRoutingRuleSummary snapshot={preview.after} /></section>
      </div> : <ClueRoutingRuleEditor disabled={busy} draft={draft} onChange={setDraft} selectFields={false} />}
    </> : null}
  </Dialog>;
}
