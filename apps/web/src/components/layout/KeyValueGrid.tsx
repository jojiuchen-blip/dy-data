import type { ReactNode } from "react";
import { IconButton } from "../Button";

export interface KeyValueItem {
  copyLabel?: string;
  copyValue?: string;
  key?: string;
  label: ReactNode;
  mono?: boolean;
  numeric?: boolean;
  value: ReactNode;
}

export interface KeyValueGridProps {
  className?: string;
  items: KeyValueItem[];
  onCopy?: (value: string, label: string) => void;
}

export function KeyValueGrid({ className, items, onCopy }: KeyValueGridProps) {
  return (
    <dl className={["ui-kv-grid", className].filter(Boolean).join(" ")}>
      {items.map((item, index) => (
        <div className="ui-kv-grid__row" key={item.key ?? `${index}`}>
          <dt className="ui-kv-grid__label">{item.label}</dt>
          <dd
            className={[
              "ui-kv-grid__value",
              item.mono ? "ui-kv-grid__value--mono" : "",
              item.numeric ? "ui-kv-grid__value--numeric" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {item.value}
          </dd>
          {item.copyValue && onCopy ? (
            <IconButton
              icon="copy"
              label={item.copyLabel ?? "复制内容"}
              onClick={() => onCopy(item.copyValue!, item.copyLabel ?? "内容")}
              size="sm"
            />
          ) : (
            <span />
          )}
        </div>
      ))}
    </dl>
  );
}
