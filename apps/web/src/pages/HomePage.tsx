import { SolarIcon } from "../components/SolarIcon";

const modules = [
  {
    description: "汇总门店分配线索、跟进状态、待再分配和转化核销情况。",
    href: "/clues",
    meta: "已接入 MVP 看板",
    status: "已接入",
    title: "线索中心",
  },
  {
    beta: true,
    description: "承接现有门店榜单、单店分账、月度明细和 SKU 分账规则管理。",
    href: "/ranking",
    meta: "试运行阶段",
    status: "已接入",
    title: "订单分佣结算中心",
  },
];

export function HomePage() {
  return (
    <main className="home-shell">
      <section className="home-heading" aria-labelledby="home-title">
        <div className="home-brand">
          <SolarIcon className="brand__mark" name="brand" size={44} />
          <div>
            <p className="eyebrow">抖音经营数据引擎</p>
            <h1 id="home-title">抖音经营数据引擎</h1>
          </div>
        </div>
      </section>

      <section className="module-grid" aria-label="业务模块入口">
        {modules.map((module) => (
          <a
            className="module-card module-card--active"
            href={module.href}
            key={module.title}
          >
            <span className="module-card__status">{module.status}</span>
            <div>
              <h2>
                {module.title}
                {module.beta ? <span className="beta-badge">试运行</span> : null}
              </h2>
              <p>{module.description}</p>
            </div>
            <span className="module-card__meta">{module.meta}</span>
          </a>
        ))}
      </section>
    </main>
  );
}
