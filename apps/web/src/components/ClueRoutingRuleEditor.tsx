import type { ClueRoutingPolicy, ClueRoutingRuleSnapshot, ClueRoutingRuleWrite } from "../api/clueRouting";
import { CheckboxField, FieldInput, SelectField } from "./FormControls";

type RuleKey = keyof ClueRoutingRuleWrite;
export type ClueRoutingRuleDraft = Record<RuleKey, { included: boolean; value: string }>;

const fields: Array<{ key: RuleKey; label: string; max?: number; defaultValue: string }> = [
  { key: "first_follow_up_sla_hours", label: "首次跟进期限（小时）", max: 168, defaultValue: "24" },
  { key: "appointment_hours", label: "已预约：预约时间后保护期（小时）", max: 8760, defaultValue: "72" },
  { key: "further_follow_up_hours", label: "待进一步跟进保护期（小时）", max: 8760, defaultValue: "168" },
  { key: "unreachable_hours", label: "未联系上保护期（小时）", max: 8760, defaultValue: "168" },
  { key: "pending_action", label: "待跟进到期动作", defaultValue: "next" },
  { key: "appointment_action", label: "已预约到期动作", defaultValue: "next" },
  { key: "further_follow_up_action", label: "待进一步跟进到期动作", defaultValue: "next" },
  { key: "unreachable_action", label: "未联系上到期动作", defaultValue: "close" },
];

export function createClueRoutingRuleDraft(snapshot?: Partial<ClueRoutingRuleSnapshot>, includeAll = false): ClueRoutingRuleDraft {
  const values = { ...snapshot?.follow_up_policy, first_follow_up_sla_hours: snapshot?.first_follow_up_sla_hours };
  return Object.fromEntries(fields.map((field) => [field.key, {
    included: includeAll,
    value: values[field.key] === undefined ? field.defaultValue : String(values[field.key]),
  }])) as ClueRoutingRuleDraft;
}

export function readClueRoutingRuleDraft(draft: ClueRoutingRuleDraft): { rules: ClueRoutingRuleWrite; error: string } {
  const rules: Record<string, number | string> = {};
  for (const field of fields) {
    const current = draft[field.key];
    if (!current.included) continue;
    if (field.max) {
      const value = Number(current.value);
      if (!Number.isInteger(value) || value < 1 || value > field.max) {
        return { rules: {}, error: `${field.label}须为 1–${field.max} 的整数。` };
      }
      rules[field.key] = value;
    } else {
      if (!["next", "close"].includes(current.value)) return { rules: {}, error: "请选择引擎支持的到期动作。" };
      rules[field.key] = current.value;
    }
  }
  return { rules: rules as ClueRoutingRuleWrite, error: Object.keys(rules).length ? "" : "请勾选至少一个要发布的规则字段。" };
}

export function ClueRoutingRuleEditor({ draft, onChange, disabled = false, selectFields = true }: {
  draft: ClueRoutingRuleDraft;
  onChange: (draft: ClueRoutingRuleDraft) => void;
  disabled?: boolean;
  selectFields?: boolean;
}) {
  return <div className="clue-routing-rule-fields">
    {fields.map((field) => <div className="clue-routing-rule-field" key={field.key}>
      {selectFields ? <CheckboxField
        checked={draft[field.key].included}
        disabled={disabled}
        label={`修改${field.label}`}
        onChange={(event) => onChange({ ...draft, [field.key]: { ...draft[field.key], included: event.target.checked } })}
      /> : null}
      {field.max ? <label className="filter-field">
        <span>{field.label}</span>
        <FieldInput
          disabled={disabled || !draft[field.key].included}
          inputMode="numeric" min={1} max={field.max} step={1} type="number"
          onChange={(event) => onChange({ ...draft, [field.key]: { ...draft[field.key], value: event.target.value } })}
          value={draft[field.key].value}
        />
      </label> : <SelectField
        disabled={disabled || !draft[field.key].included}
        label={field.label}
        onChange={(value) => onChange({ ...draft, [field.key]: { ...draft[field.key], value } })}
        options={[{ value: "next", label: "按轮次续派或关闭" }, { value: "close", label: "关闭" }]}
        value={draft[field.key].value}
      />}
    </div>)}
  </div>;
}

function expiryLabel(value: ClueRoutingPolicy[keyof ClueRoutingPolicy] | undefined) {
  return value === "next" ? "按轮次续派或关闭" : value === "close" ? "关闭" : "未配置";
}

export function ClueRoutingRuleSummary({ snapshot }: { snapshot: Partial<ClueRoutingRuleSnapshot> }) {
  const policy = snapshot.follow_up_policy;
  const hours = (value: number | undefined) => value === undefined ? "未配置" : `${value} 小时`;
  return <dl className="clue-routing-rule-summary">
    <div><dt>首次跟进</dt><dd>{hours(snapshot.first_follow_up_sla_hours)}；到期{expiryLabel(policy?.pending_action)}</dd></div>
    <div><dt>已预约</dt><dd>预约时间后 {hours(policy?.appointment_hours)}；到期{expiryLabel(policy?.appointment_action)}</dd></div>
    <div><dt>进一步跟进</dt><dd>{hours(policy?.further_follow_up_hours)}；到期{expiryLabel(policy?.further_follow_up_action)}</dd></div>
    <div><dt>未联系上</dt><dd>{hours(policy?.unreachable_hours)}；到期{expiryLabel(policy?.unreachable_action)}</dd></div>
  </dl>;
}
