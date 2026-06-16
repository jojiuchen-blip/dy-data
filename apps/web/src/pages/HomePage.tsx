const modules = [
  {
    description: "承接现有门店榜单、单店分账、月度明细和 SKU 分佣规则管理。",
    href: "/ranking",
    meta: "已接入当前项目内容",
    status: "已接入",
    title: "订单结算中心",
  },
  {
    description: "后续规划线索汇入、门店分配、跟进状态和转化回流。",
    meta: "待规划",
    status: "待规划",
    title: "线索跟进分配中心",
  },
];

export function HomePage() {
  return (
    <main className="home-shell">
      <section className="home-heading" aria-labelledby="home-title">
        <div className="home-brand">
          <img
            aria-hidden="true"
            className="brand__mark"
            src="/business-loop-icon.svg"
            alt=""
          />
          <div>
            <p className="eyebrow">Douyin business data engine</p>
            <h1 id="home-title">抖音经营数据引擎</h1>
          </div>
        </div>
      </section>

      <section className="module-grid" aria-label="业务模块入口">
        {modules.map((module) =>
          module.href ? (
            <a className="module-card module-card--active" href={module.href} key={module.title}>
              <span className="module-card__status">{module.status}</span>
              <div>
                <h2>{module.title}</h2>
                <p>{module.description}</p>
              </div>
              <span className="module-card__meta">{module.meta}</span>
            </a>
          ) : (
            <article
              aria-disabled="true"
              className="module-card module-card--planned"
              key={module.title}
            >
              <span className="module-card__status">{module.status}</span>
              <div>
                <h2>{module.title}</h2>
                <p>{module.description}</p>
              </div>
              <span className="module-card__meta">{module.meta}</span>
            </article>
          ),
        )}
      </section>
    </main>
  );
}
