import { chromium } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";

const signoz = (process.env.SIGNOZ_INTERNAL_URL ?? "http://orbital-signoz-0:8080").replace(/\/$/, "");
const email = process.env.SIGNOZ_ADMIN_EMAIL;
const password = process.env.SIGNOZ_ADMIN_PASSWORD;
const output = process.env.ORBITAL_SIGNOZ_ASSET_OUTPUT ?? "apps/mission-control/signoz-assets";
const finalDemo = JSON.parse(
  await readFile("/workspace/data/demo-output/final-demo.json", "utf8"),
);
const alerts = JSON.parse(
  await readFile("/workspace/data/demo-output/phase2-alert-verification.json", "utf8"),
);

if (!email || !password) {
  throw new Error("SigNoz local admin credentials are required for screenshot capture");
}

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1366, height: 768 },
  reducedMotion: "reduce",
  deviceScaleFactor: 1,
});

async function settle() {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(2_000);
}

async function capture(filename) {
  await settle();
  const bodyText = (await page.locator("body").innerText()).trim();
  if (bodyText.length < 20) {
    throw new Error(
      `SigNoz page did not render evidence (${page.url()}): ${bodyText || "empty body"}`,
    );
  }
  console.log(`Capturing ${filename}: ${page.url()} :: ${bodyText.slice(0, 120)}`);
  await page.screenshot({ path: path.join(output, filename), fullPage: false });
}

await page.goto(signoz, { waitUntil: "domcontentloaded" });
await settle();
if (
  page.url().includes("/login")
  || (await page.locator("body").innerText()).toLowerCase().includes("sign in to your workspace")
) {
  const emailInput = page.locator('input[type="email"], input').first();
  await emailInput.waitFor({ state: "visible", timeout: 10_000 });
  await emailInput.fill(email);
  await page.getByRole("button", { name: /next|continue/i }).click();
  const passwordInput = page.locator('input[type="password"]').first();
  await passwordInput.waitFor({ state: "visible", timeout: 10_000 });
  await passwordInput.fill(password);
  await page.getByRole("button", { name: /sign in|login|next|continue/i }).click();
  await page.waitForURL((url) => !url.pathname.includes("login"), { timeout: 30_000 });
}

const traceId = finalDemo.evidence_parity.trace_id;
await page.goto(`${signoz}/trace/${traceId}`, { waitUntil: "domcontentloaded" });
await capture("01-evidence-trace.png");

await page.goto(`${signoz}/dashboard`, { waitUntil: "domcontentloaded" });
await settle();
const readiness = page.getByText(/Flight Readiness/i).first();
await readiness.waitFor({ state: "visible", timeout: 15_000 });
await readiness.click();
await page.waitForURL((url) => url.pathname !== "/dashboard", { timeout: 15_000 });
await capture("02-flight-readiness-dashboard.png");

await page.goto(`${signoz}/dashboard`, { waitUntil: "domcontentloaded" });
await settle();
const integrity = page.getByText(/Evidence Integrity/i).first();
await integrity.waitFor({ state: "visible", timeout: 15_000 });
await integrity.click();
await page.waitForURL((url) => url.pathname !== "/dashboard", { timeout: 15_000 });
await capture("03-trace-funnel.png");

const artifactAlert = alerts.history["ORBITAL Artifact Drift"];
if (!artifactAlert?.web_url) {
  throw new Error("Artifact Drift alert-history URL is absent");
}
const alertURL = new URL(artifactAlert.web_url);
await page.goto(`${signoz}${alertURL.pathname}${alertURL.search}`, {
  waitUntil: "domcontentloaded",
});
await settle();
const historyTab = page.locator(".ant-tabs-tab").filter({ hasText: "History" }).first();
await historyTab.waitFor({ state: "visible", timeout: 15_000 });
await historyTab.click();
await page.waitForTimeout(3_000);
await capture("04-alert-history.png");

await browser.close();
console.log(`Captured live SigNoz trace, dashboards, funnel, and alert history in ${output}`);
