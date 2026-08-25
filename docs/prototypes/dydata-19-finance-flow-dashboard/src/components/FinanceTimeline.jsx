import { timelineSteps } from "../data/financeData.js";
import { SolarIcon } from "./SolarIcon.jsx";

export function FinanceTimeline({ scenario }) {
  return (
    <section className="timeline-panel" aria-labelledby="timeline-title">
      <div className="section-heading timeline-panel__heading">
        <div>
          <span className="eyebrow">月度节奏</span>
          <h2 id="timeline-title">从月末排查到审核结算</h2>
        </div>
        <p>6日与10日均以北京时间自然日24:00为界。</p>
      </div>
      <ol className="finance-timeline">
        {timelineSteps.map((step, index) => (
          <li
            key={step.id}
            className={step.id === scenario.activeStep ? "is-current" : ""}
            aria-current={step.id === scenario.activeStep ? "step" : undefined}
          >
            <span className="finance-timeline__node">{index + 1}</span>
            <div>
              <strong>{step.label}</strong>
              <time>{step.time}</time>
              <small>{step.detail}</small>
            </div>
          </li>
        ))}
      </ol>
      <div className={`scenario-notice scenario-notice--${scenario.tone}`} role="status">
        <SolarIcon name={scenario.tone === "danger" ? "danger" : "info"} />
        <div>
          <strong>{scenario.title}</strong>
          <span>{scenario.notice}</span>
        </div>
      </div>
    </section>
  );
}
