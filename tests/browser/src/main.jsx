import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.jsx";

// Keep the transport compatibility harness single-shot. React development
// StrictMode intentionally re-runs effects as setup -> cleanup -> setup, and
// App cleanup cancels the active grpc-web stream. That creates two XHRs for a
// single test case and introduces a browser-specific cancel/restart race that
// does not exist in a production React build.
createRoot(document.getElementById("root")).render(<App />);
