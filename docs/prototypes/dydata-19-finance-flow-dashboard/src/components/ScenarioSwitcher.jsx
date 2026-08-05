import { scenarioFixtures } from "../data/financeData.js";

export function ScenarioSwitcher({ value, onChange, onApply }) {
  const current = scenarioFixtures[value];

  return (
    <section className="scenario-switcher" aria-labelledby="scenario-title">
      <div>
        <span className="eyebrow">会议演示</span>
        <h2 id="scenario-title">F01—F10 验收场景</h2>
        <p>{current.summary}</p>
      </div>
      <label>
        <span>选择场景</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          {Object.entries(scenarioFixtures).map(([id, scenario]) => (
            <option key={id} value={id}>
              {id} · {scenario.title}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="button button--secondary" onClick={() => onApply(current)}>
        跳转到场景页面
      </button>
    </section>
  );
}
