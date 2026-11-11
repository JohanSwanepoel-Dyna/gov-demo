#!/usr/bin/env node
// Browser load for the portal, run on demand. Each session is a fresh browser context, so RUM sees a new session.
//   node run.mjs --profile completer --sessions 5 --concurrency 3
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { values: opt } = parseArgs({
  options: {
    "base-url": { type: "string", default: process.env.BASE_URL || "http://localhost:8080" },
    profile: { type: "string", default: "completer" },
    sessions: { type: "string", default: "3" },
    concurrency: { type: "string", default: "3" },
    credentials: { type: "string", default: path.join(here, "../../db/out/credentials.csv") },
    headed: { type: "boolean", default: false },
    bundled: { type: "boolean", default: false },
  },
});
const PROFILES = ["completer", "abandoner", "assistant"];
if (!PROFILES.includes(opt.profile)) { console.error(`profile must be one of ${PROFILES.join(", ")}`); process.exit(2); }

// Skip ids divisible by 20: those citizens are non-residents and are always ineligible.
const citizens = readFileSync(opt.credentials, "utf8").trim().split("\n").slice(1)
  .map((l) => l.split(",")).map(([id, pc]) => ({ id: Number(id), pc: pc.trim() })).filter((c) => c.id % 20 !== 0);
const pick = () => citizens[Math.floor(Math.random() * citizens.length)];
const think = (page) => page.waitForTimeout(1000 + Math.random() * 2500);
const FILE = { name: "statement.txt", mimeType: "text/plain", buffer: Buffer.from("Demonstration supporting document.\nCarer statement (fictional).\n") };

async function signIn(page, c, steps) {
  await page.goto(opt["base-url"]);
  await page.getByLabel("Citizen ID").fill(String(c.id));
  await page.getByLabel("Passcode").fill(c.pc);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: /^Good (morning|afternoon|evening)/ }).waitFor();
  steps.push("login");
  await page.getByRole("link", { name: /Carer Support/ }).first().click();
  await page.getByLabel("Payment type").waitFor();
}

// Login to the upload step. Returns false when the claim is not eligible.
async function toUpload(page, c, steps) {
  await signIn(page, c, steps);
  await think(page);
  await page.getByLabel("Payment type").selectOption(Math.random() < 0.7 ? "carer_payment" : "carer_allowance");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Household income band").waitFor();
  steps.push("payment-type");
  await think(page);
  await page.getByLabel("Household income band").selectOption("low");
  await page.getByLabel("Caring hours per week").fill(String(30 + Math.floor(Math.random() * 15)));
  await page.getByRole("button", { name: "Check eligibility" }).click();
  await page.getByRole("heading", { name: "Eligibility result" }).waitFor();
  steps.push("details", "eligibility");
  if (!(await page.getByRole("button", { name: "Continue" }).count())) return false;
  await think(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Document").waitFor();
  steps.push("upload");
  return true;
}

const journeys = {
  async completer(page, c, steps) {
    if (!(await toUpload(page, c, steps))) return "ineligible";
    await think(page);
    await page.getByLabel("Document").setInputFiles(FILE);
    await page.getByRole("button", { name: "Upload" }).click();
    await page.getByRole("heading", { name: "Review and submit" }).waitFor();
    steps.push("review");
    await think(page);
    await page.getByRole("button", { name: "Submit claim" }).click();
    await page.getByRole("heading", { name: "Claim status" }).waitFor();
    steps.push("status");
    const outcome = await Promise.race([
      page.getByText("Payment has been processed.").waitFor({ timeout: 90000 }).then(() => "paid"),
      page.getByText("Payment failed").waitFor({ timeout: 90000 }).then(() => "payment_failed"),
    ]).catch(() => "timeout");
    return outcome;
  },
  async abandoner(page, c, steps) {
    if (!(await toUpload(page, c, steps))) return "ineligible";
    await page.waitForTimeout(2000 + Math.random() * 3000); // looks at the upload step, then leaves
    return "abandoned_at_upload";
  },
  async assistant(page, c, steps) {
    await signIn(page, c, steps);
    await page.locator(".chat").waitFor();
    if (!(await page.locator(".chat-body").isVisible())) await page.locator(".chat-toggle").click();  // collapsed by default
    for (const label of ["Quick check: 35 hours, low income", "Documents"]) {
      const before = await page.locator(".chat-bot").count();
      await think(page);
      await page.getByRole("button", { name: label }).click();
      await page.waitForFunction((n) => document.querySelectorAll(".chat-bot").length > n, before, { timeout: 60000 });
      steps.push("assistant: " + label);
    }
    return "answered";
  },
};

async function session(browser, n) {
  const c = pick(), steps = [], started = Date.now();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  let outcome;
  try {
    outcome = await journeys[opt.profile](page, c, steps);
  } catch (e) {
    outcome = "error: " + e.message.split("\n")[0].slice(0, 90);
  } finally {
    await context.close(); // ends the RUM session
  }
  const row = { n, citizen: c.id, outcome, seconds: Math.round((Date.now() - started) / 1000), last_step: steps.at(-1) || "-" };
  console.log(`session ${n}: citizen ${c.id} ${outcome} after ${row.seconds}s (last step ${row.last_step})`);
  return row;
}

const total = Number(opt.sessions), width = Math.max(1, Number(opt.concurrency));
const browser = await chromium.launch({ headless: !opt.headed, ...(opt.bundled ? {} : { channel: "chrome" }) });
console.log(`profile ${opt.profile}: ${total} sessions, concurrency ${width}, ${opt["base-url"]}`);
let next = 0;
const results = [];
await Promise.all(Array.from({ length: Math.min(width, total) }, async () => {
  while (next < total) results.push(await session(browser, ++next));
}));
await browser.close();

const counts = results.reduce((m, r) => ((m[r.outcome.split(":")[0]] = (m[r.outcome.split(":")[0]] || 0) + 1), m), {});
console.log("summary:", JSON.stringify(counts));
const bad = results.filter((r) => r.outcome.startsWith("error") || r.outcome === "timeout");
process.exit(bad.length ? 1 : 0);
