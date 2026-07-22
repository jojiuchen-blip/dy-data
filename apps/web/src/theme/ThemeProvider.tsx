import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const THEME_STORAGE_KEY = "dydata.theme.preference";
const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

interface ThemeContextValue {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function isThemePreference(value: string | null | undefined): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function initialPreference(): ThemePreference {
  const bootstrapPreference = document.documentElement.dataset.themePreference;
  if (isThemePreference(bootstrapPreference)) {
    return bootstrapPreference;
  }
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

function applyTheme(preference: ThemePreference, resolvedTheme: ResolvedTheme) {
  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.style.colorScheme = resolvedTheme;
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (themeColor) {
    const resolvedThemeColor = window
      .getComputedStyle(document.documentElement)
      .getPropertyValue("--browser-theme-color")
      .trim();
    if (resolvedThemeColor) {
      themeColor.content = resolvedThemeColor;
    }
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const mediaQuery = useMemo(() => window.matchMedia("(prefers-color-scheme: dark)"), []);
  const [preference, setPreferenceState] = useState<ThemePreference>(initialPreference);
  const [systemPrefersDark, setSystemPrefersDark] = useState(mediaQuery.matches);
  const resolvedTheme = resolveTheme(preference, systemPrefersDark);

  useEffect(() => {
    const handleSystemThemeChange = (event: MediaQueryListEvent) => {
      setSystemPrefersDark(event.matches);
    };
    mediaQuery.addEventListener("change", handleSystemThemeChange);
    return () => mediaQuery.removeEventListener("change", handleSystemThemeChange);
  }, [mediaQuery]);

  useEffect(() => {
    applyTheme(preference, resolvedTheme);
  }, [preference, resolvedTheme]);

  const setPreference = useCallback((nextPreference: ThemePreference) => {
    setPreferenceState(nextPreference);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextPreference);
    } catch {
      // Theme selection remains effective for the current session when storage is unavailable.
    }
  }, []);

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference }),
    [preference, resolvedTheme, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
