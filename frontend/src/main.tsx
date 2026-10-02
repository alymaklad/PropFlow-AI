import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Base styles first, so component styles (imported by the app) can refine them.
import "./styles/tokens.css";
import "./styles/base.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
