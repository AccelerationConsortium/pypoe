import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// Shared SDL2 lab auth banner (served by ac_auth at the edge). Injected at
// runtime with an ABSOLUTE root path ("/auth/banner.js") so Vite's base
// (e.g. "/pypoe-next/") does NOT rewrite it — the banner and its /auth/* calls
// must resolve at the edge ROOT, not under this app's prefix. It renders the
// shared top bar consistent with every other lab UI, and 404s harmlessly when
// not served behind the edge (e.g. hitting the dev server directly).
if (
  typeof document !== "undefined" &&
  !document.getElementById("ac-auth-banner-loader")
) {
  const s = document.createElement("script");
  s.id = "ac-auth-banner-loader";
  s.src = "/auth/banner.js";
  s.defer = true;
  document.head.appendChild(s);
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
