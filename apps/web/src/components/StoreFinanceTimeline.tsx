type StoreFinanceStage = "confirmation" | "invoice" | "status";

interface StoreFinanceTimelineProps {
  activeStage: StoreFinanceStage;
  statusText: string;
  statusTitle: string;
}

const STORE_FINANCE_STEPS = [
  { label: "月度结束", meta: "每月最后一日" },
  { label: "系统核查", meta: "次月1日" },
  { label: "账单确认", meta: "次月1—6日" },
  { label: "自动确认", meta: "次月6日24:00" },
  { label: "发票提交", meta: "当月10日前" },
  { label: "厂端审核", meta: "以厂端结果为准" },
  { label: "审核通过/已结算", meta: "以实际结算为准" },
] as const;

const ACTIVE_STEP_INDEX: Record<StoreFinanceStage, number> = {
  confirmation: 2,
  invoice: 4,
  status: 5,
};

export function StoreFinanceTimeline({
  activeStage,
  statusText,
  statusTitle,
}: StoreFinanceTimelineProps) {
  const activeIndex = ACTIVE_STEP_INDEX[activeStage];

  return (
    <section className="store-finance-timeline" aria-label="月度结算进度">
      <ol className="store-finance-timeline__steps">
        {STORE_FINANCE_STEPS.map((step, index) => (
          <li
            aria-current={index === activeIndex ? "step" : undefined}
            className={[
              "store-finance-timeline__step",
              index < activeIndex ? "is-complete" : "",
              index === activeIndex ? "is-current" : "",
            ].filter(Boolean).join(" ")}
            key={step.label}
          >
            <span className="store-finance-timeline__marker" aria-hidden="true">
              {index + 1}
            </span>
            <strong>{step.label}</strong>
            <span>{step.meta}</span>
          </li>
        ))}
      </ol>
      <div className="store-finance-timeline__status" role="status">
        <strong>{statusTitle}</strong>
        <span>{statusText}</span>
      </div>
    </section>
  );
}
