import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../design-tokens.css";
import "../styles.css";
import "./catalog.css";
import { ThemeProvider } from "../theme/ThemeProvider";
import { DesignSystemCatalog } from "./DesignSystemCatalog";

const params = new URLSearchParams(window.location.search);
const requestedTheme = params.get("theme");
document.documentElement.dataset.theme = requestedTheme === "dark" ? "dark" : "light";
document.documentElement.dataset.themePreference = requestedTheme === "dark" ? "dark" : "light";
document.documentElement.dataset.embedded = String(params.get("embedded") === "1");

const root = document.getElementById("root");
if (!root) {
  throw new Error("Design system catalog root is missing.");
}

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <DesignSystemCatalog />
    </ThemeProvider>
  </StrictMode>,
);
