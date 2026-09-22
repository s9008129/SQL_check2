import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/app.css";
import "./styles/tokens.css";
import "./styles/visual-storytelling.css";
import "./styles/print.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
