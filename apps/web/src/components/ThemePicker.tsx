import type { ThemePreference } from "../theme/ThemeProvider";
import { useTheme } from "../theme/ThemeProvider";
import { SolarIcon, type SolarIconName } from "./SolarIcon";

const options: Array<{
  icon: SolarIconName;
  label: string;
  value: ThemePreference;
}> = [
  { icon: "monitor", label: "跟随系统", value: "system" },
  { icon: "sun", label: "浅色", value: "light" },
  { icon: "moon", label: "深色", value: "dark" },
];

interface ThemePickerProps {
  className?: string;
  compact?: boolean;
}

export function ThemePicker({ className, compact = false }: ThemePickerProps) {
  const { preference, setPreference } = useTheme();

  return (
    <div
      aria-label="界面主题"
      className={[
        "theme-picker",
        compact ? "theme-picker--compact" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      role="group"
    >
      {options.map((option) => (
        <button
          aria-pressed={preference === option.value}
          className="theme-picker__option"
          key={option.value}
          onClick={() => setPreference(option.value)}
          title={compact ? option.label : undefined}
          type="button"
        >
          <SolarIcon name={option.icon} size={17} />
          <span>{option.label}</span>
        </button>
      ))}
    </div>
  );
}
