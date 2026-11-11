import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.PORT || 8080);
const ACCESS_LOG = process.env.ACCESS_LOG === "on";
const CLAIMS_API_URL = process.env.CLAIMS_API_URL || "http://claims-api:8000";
const here = path.dirname(fileURLToPath(import.meta.url));
const app = express();

function log(msg, fields = {}) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level: "INFO", service: "web", msg, ...fields }));
}

app.use((req, res, next) => {
  const start = Date.now();
  res.on("finish", () => (ACCESS_LOG || res.statusCode >= 400 || Date.now() - start > 1000) && log("request", { method: req.method, path: req.path, status: res.statusCode, ms: Date.now() - start }));
  next();
});

app.get("/healthz", (req, res) => res.json({ status: "ok" }));

// Proxy /api/* untouched (request bodies are streamed, trace headers are forwarded).
// Each endpoint is its own Express route, so OneAgent reports a meaningful http.route (for example
// /api/claims/:claimId/eligibility) instead of "/" for every proxied call.
const apiProxy = createProxyMiddleware({ target: CLAIMS_API_URL, changeOrigin: true, pathFilter: "/api/" });
const API_ROUTES = [
  "/api/login",
  "/api/home",
  "/api/claims",
  "/api/claims/:claimId",
  "/api/claims/:claimId/eligibility",
  "/api/claims/:claimId/documents",
  "/api/claims/:claimId/submit",
  "/api/assistant",
];
for (const route of API_ROUTES) app.all(route, apiProxy);
app.use("/api/", apiProxy);  // anything not listed above still reaches claims-api

app.use(express.static(path.join(here, "public")));
// Each step of the journey is a URL of its own. Serve the single page app for all of them.
app.get(/^\/(login|home|inbox|payment-type|details|eligibility|upload|review|status)$/, (req, res) =>
  res.sendFile(path.join(here, "public", "index.html")));

app.listen(PORT, "0.0.0.0", () => log("web started", { port: PORT, claims_api: CLAIMS_API_URL }));
