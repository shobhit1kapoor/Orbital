import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://mission-control:3000";
const output = process.env.ORBITAL_ASSET_OUTPUT ?? "apps/mission-control/docs-assets";
const screens = [
  ["Launch Console", "01-launch-console.png"],
  ["Evidence Parity", "02-evidence-parity.png"],
  ["Replay Theater", "03-replay-theater.png"],
  ["Causal Graph", "04-causal-graph.png"],
  ["Authority Frontier", "05-authority-frontier.png"],
  ["Safety Case", "06-safety-case.png"],
  ["Certificate", "07-certificate.png"],
];

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1366, height: 768 },
  reducedMotion: "reduce",
  deviceScaleFactor: 1,
});

await page.goto(baseURL, { waitUntil: "networkidle" });
await page.waitForFunction(() => {
  const body = document.body.innerText;
  return body.includes("EVIDENCE PLANE CONNECTED") && !body.includes("Loading flight data");
}, { timeout: 30_000 });

for (const [label, filename] of screens) {
  await page.getByRole("button", { name: label, exact: true }).click();
  await page.getByRole("heading", { name: label, exact: true }).waitFor();
  await page.screenshot({
    path: path.join(output, filename),
    fullPage: false,
  });
}

await browser.close();
console.log(`Captured ${screens.length} live Mission Control screens in ${output}`);
