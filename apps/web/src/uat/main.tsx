import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { UatPreviewApp } from "./UatPreviewApp";
import "../styles.css";
import "./uat-preview.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UatPreviewApp />
  </StrictMode>,
);
