import { useEffect, useState } from "react";
import { RoleBadge, StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { SelectField } from "../components/FormControls";
import { fetchFeedback, updateFeedbackStatus } from "../api/client";
import type {
  FeedbackCategory,
  FeedbackListData,
  FeedbackRow,
  FeedbackStatus,
} from "../types/dashboard";
import { formatDateTime } from "../utils/format";

const PAGE_SIZE = 20;

const categoryOptions: Array<{ label: string; value: FeedbackCategory | "" }> = [
  { label: "全部类型", value: "" },
  { label: "使用体验", value: "experience" },
  { label: "数据问题", value: "data" },
  { label: "功能建议", value: "feature" },
  { label: "其他", value: "other" },
];

const statusOptions: Array<{ label: string; value: FeedbackStatus | "" }> = [
  { label: "全部", value: "" },
  { label: "未处理", value: "new" },
  { label: "已读", value: "reviewed" },
  { label: "已处理", value: "resolved" },
  { label: "忽略", value: "ignored" },
];

const categoryLabels: Record<FeedbackCategory, string> = {
  data: "数据问题",
  experience: "使用体验",
  feature: "功能建议",
  other: "其他",
};

const statusLabels: Record<FeedbackStatus, string> = {
  ignored: "忽略",
  new: "未处理",
  resolved: "已处理",
  reviewed: "已读",
};

const feedbackStatusTones: Record<FeedbackStatus, "blue" | "danger" | "green" | "neutral"> = {
  ignored: "neutral",
  new: "danger",
  resolved: "green",
  reviewed: "blue",
};

const statusActions: Array<{ label: string; value: FeedbackStatus }> = [
  { label: "标记已读", value: "reviewed" },
  { label: "已处理", value: "resolved" },
  { label: "忽略", value: "ignored" },
];

function totalStatusCount(data: FeedbackListData | null): number {
  return Object.values(data?.status_counts ?? {}).reduce(
    (total, value) => total + value,
    0,
  );
}

function countForStatus(data: FeedbackListData | null, status: FeedbackStatus): number {
  return data?.status_counts?.[status] ?? 0;
}

export function AdminFeedbackPage() {
  const [category, setCategory] = useState<FeedbackCategory | "">("");
  const [status, setStatus] = useState<FeedbackStatus | "">("new");
  const [searchDraft, setSearchDraft] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<FeedbackListData | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const loadFeedback = () => {
    setLoading(true);
    setMessage("");
    fetchFeedback({
      category,
      page,
      pageSize: PAGE_SIZE,
      q: query,
      status,
    })
      .then((response) => setData(response.data))
      .catch(() => {
        setMessage("用户建议暂时无法读取，请确认当前账号具有管理员权限。");
        setData(null);
      })
      .finally(() => setLoading(false));
  };

  useEffect(loadFeedback, [category, page, query, status]);

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(1);
    setQuery(searchDraft.trim());
  };

  const clearFilters = () => {
    setCategory("");
    setStatus("new");
    setSearchDraft("");
    setQuery("");
    setPage(1);
  };

  const changeStatus = async (feedbackId: string, nextStatus: FeedbackStatus) => {
    setUpdatingId(feedbackId);
    setMessage("");
    try {
      await updateFeedbackStatus(feedbackId, nextStatus);
      setMessage("建议状态已更新。");
      loadFeedback();
    } catch {
      setMessage("状态更新失败，请稍后重试。");
    } finally {
      setUpdatingId(null);
    }
  };

  const rows = data?.rows ?? [];
  const pagination = data?.pagination;
  const total = pagination?.total ?? 0;
  const totalPages = pagination?.total_pages ?? 1;

  const columns: Column<FeedbackRow>[] = [
    {
      key: "created_at",
      minWidth: 150,
      title: "提交时间",
      render: (row) => formatDateTime(row.created_at),
    },
    {
      key: "category",
      minWidth: 96,
      title: "类型",
      render: (row) => <RoleBadge>{categoryLabels[row.category]}</RoleBadge>,
    },
    {
      key: "status",
      minWidth: 86,
      title: "状态",
      render: (row) => (
        <StatusChip tone={feedbackStatusTones[row.status]}>
          {statusLabels[row.status]}
        </StatusChip>
      ),
    },
    {
      key: "content",
      minWidth: 360,
      title: "建议内容",
      render: (row) => <p className="feedback-content-cell">{row.content}</p>,
    },
    {
      key: "user",
      minWidth: 140,
      title: "提交账号",
      render: (row) => (
        <span>
          {row.username || "-"}
          {row.user_role ? <small className="feedback-user-role">{row.user_role}</small> : null}
        </span>
      ),
    },
    {
      key: "contact",
      minWidth: 150,
      title: "联系方式",
      render: (row) => row.contact || "-",
    },
    {
      key: "page_path",
      minWidth: 120,
      title: "页面",
      render: (row) => <span className="mono-cell">{row.page_path || "-"}</span>,
    },
    {
      align: "center",
      key: "actions",
      minWidth: 220,
      title: "处理",
      render: (row) => (
        <div className="table-action-row">
          {statusActions.map((action) => (
            <button
              className="ghost-button"
              disabled={updatingId === row.feedback_id || row.status === action.value}
              key={action.value}
              onClick={() => changeStatus(row.feedback_id, action.value)}
              type="button"
            >
              {updatingId === row.feedback_id ? "更新中" : action.label}
            </button>
          ))}
        </div>
      ),
    },
  ];

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <h1>用户建议</h1>
          <p className="admin-muted">查看用户提交的体验反馈、数据问题和功能建议。</p>
        </div>
        <div className="admin-header-actions">
          {loading ? <span className="source-pill">加载中</span> : null}
          <button className="ghost-button" onClick={loadFeedback} type="button">
            刷新
          </button>
        </div>
      </section>

      <section className="feedback-summary-row" aria-label="建议处理状态">
        {statusOptions.map((item) => {
          const count =
            item.value === ""
              ? totalStatusCount(data)
              : countForStatus(data, item.value);
          return (
            <button
              aria-pressed={status === item.value}
              className="feedback-summary-button"
              key={item.value || "all"}
              onClick={() => {
                setStatus(item.value);
                setPage(1);
              }}
              type="button"
            >
              <span>{item.label}</span>
              <strong>{count}</strong>
            </button>
          );
        })}
      </section>

      <form className="filter-bar admin-feedback-filters" onSubmit={submitSearch}>
        <SelectField
          label="建议类型"
          onChange={(value) => {
            setCategory(value as FeedbackCategory | "");
            setPage(1);
          }}
          options={categoryOptions}
          value={category}
        />
        <label className="filter-field">
          <span>关键词</span>
          <input
            onChange={(event) => setSearchDraft(event.target.value)}
            placeholder="搜索内容、账号、页面或联系方式"
            value={searchDraft}
          />
        </label>
        <button className="primary-button" type="submit">
          查询
        </button>
        <button className="ghost-button" onClick={clearFilters} type="button">
          清空筛选
        </button>
      </form>

      {message ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice"
          role="status"
        >
          {message}
        </div>
      ) : null}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>建议列表</h2>
            <p>
              当前筛选 {total} 条，默认优先处理未处理建议。
            </p>
          </div>
          {query ? <span className="source-pill">关键词：{query}</span> : null}
        </div>
        <DataTable
          columns={columns}
          emptyText={loading ? "正在加载用户建议..." : "当前筛选下暂无用户建议"}
          rows={rows}
          tableClassName="admin-feedback-table"
        />
        <div className="pagination-controls">
          <span className="pagination-controls__summary">
            第 {page} / {totalPages} 页
          </span>
          <div className="pagination-controls__actions">
            <button
              className="ghost-button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              type="button"
            >
              上一页
            </button>
            <button
              className="ghost-button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((current) => current + 1)}
              type="button"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
