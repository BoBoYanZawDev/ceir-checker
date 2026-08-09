import "server-only";

import { createHash } from "node:crypto";
import path from "node:path";
import { chromium, type BrowserContext, type Page } from "playwright";

const CEIR_BASE = "https://ceir.gov.mm";
const CHALLENGE_TITLES = ["just a moment", "ddos-guard", "checking your browser", "please wait"];
const isHeadless = () => process.env.CEIR_HEADLESS === "true";

type BridgeResponse = { ok: boolean; status: number; text: string; error?: string };
type BrowserState = { context: BrowserContext | null; page: Page | null; queue: Promise<void> };

declare global {
  var __ceirBrowserState: BrowserState | undefined;
}

const state: BrowserState = globalThis.__ceirBrowserState ?? { context: null, page: null, queue: Promise.resolve() };
globalThis.__ceirBrowserState = state;

export class CeirError extends Error {
  constructor(message: string, public readonly status = 502, public readonly code = "CEIR_ERROR") {
    super(message);
  }
}

async function launchContext(): Promise<BrowserContext> {
  if (state.context) return state.context;

  const profileDir = process.env.CEIR_PROFILE_DIR ?? path.join(process.cwd(), ".ceir-profile");
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: isHeadless(),
    viewport: { width: 1280, height: 900 },
    locale: "en-US",
    timezoneId: "Asia/Yangon",
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
  });
  context.on("close", () => { state.context = null; state.page = null; });
  state.context = context;
  return context;
}

async function getReadyPage(forceReload = false): Promise<Page> {
  const context = await launchContext();
  let page = state.page && !state.page.isClosed() ? state.page : context.pages()[0];
  if (!page || page.isClosed()) page = await context.newPage();
  state.page = page;

  if (forceReload || !page.url().includes("ceir.gov.mm")) {
    await page.goto(CEIR_BASE, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => undefined);
  }

  const deadline = Date.now() + Number(process.env.CEIR_READY_TIMEOUT_MS ?? 90_000);
  while (Date.now() < deadline) {
    const title = (await page.title().catch(() => "")).toLowerCase();
    const url = page.url();
    const body = await page.locator("body").innerText({ timeout: 1_000 }).catch(() => "");
    if (/access restricted|only accessible from myanmar/i.test(`${title} ${body}`)) {
      throw new CeirError("CEIR is geo-blocked. Run the browser worker from a Myanmar IP and turn off foreign VPNs.", 403, "GEO_BLOCKED");
    }
    const challenged = CHALLENGE_TITLES.some((marker) => title.includes(marker));
    if (url.includes("ceir.gov.mm") && title && !challenged) return page;
    await page.waitForTimeout(500);
  }
  throw new CeirError(
    !isHeadless()
      ? "Cloudflare challenge was not completed. Complete it in the worker browser and retry."
      : "Cloudflare challenge persists. Start with CEIR_HEADLESS=false once to establish the persistent session.",
    503,
    "CF_CHALLENGE",
  );
}

async function bridgeFetch(page: Page, pathname: string, init?: { method?: string; body?: string; headers?: Record<string, string> }): Promise<BridgeResponse> {
  const url = pathname.startsWith("http") ? pathname : `${CEIR_BASE}${pathname}`;
  return page.evaluate(async ({ requestUrl, requestInit }) => {
    try {
      const response = await fetch(requestUrl, { ...requestInit, credentials: "include" });
      return { ok: response.ok, status: response.status, text: await response.text() };
    } catch (error) {
      return { ok: false, status: 0, text: "", error: error instanceof Error ? error.message : String(error) };
    }
  }, { requestUrl: url, requestInit: init });
}

async function solveAltcha(challenge: { algorithm: string; challenge: string; maxnumber?: number; salt: string; signature: string }): Promise<string> {
  const startedAt = Date.now();
  const max = challenge.maxnumber ?? 1_000_000;
  for (let number = 0; number < max; number += 1) {
    if (createHash("sha256").update(challenge.salt + number).digest("hex") === challenge.challenge) {
      return Buffer.from(JSON.stringify({ ...challenge, number, took: Date.now() - startedAt, maxnumber: undefined })).toString("base64");
    }
    if (number > 0 && number % 50_000 === 0) await new Promise((resolve) => setImmediate(resolve));
  }
  throw new CeirError("ALTCHA proof-of-work could not be solved.", 502, "ALTCHA_SOLVE_FAILED");
}

async function getAltchaToken(page: Page): Promise<string> {
  let lastError = "unknown error";
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const response = await bridgeFetch(page, "/openapi/API/Auth/altcha/altcha");
    if (response.status === 403 && /access restricted|only accessible from myanmar/i.test(response.text)) {
      throw new CeirError("CEIR only accepts requests from a Myanmar IP.", 403, "GEO_BLOCKED");
    }
    if (response.ok && response.status === 200) {
      try {
        const challenge = JSON.parse(response.text) as { algorithm: string; challenge: string; maxnumber?: number; salt: string; signature: string };
        if (challenge.challenge && challenge.salt) return await solveAltcha(challenge);
        lastError = "challenge response is missing required fields";
      } catch (error) {
        lastError = error instanceof Error ? error.message : "invalid ALTCHA response";
      }
    } else {
      lastError = response.error ?? `HTTP ${response.status}`;
    }
    if (attempt < 3) await page.waitForTimeout(attempt * 800);
  }
  throw new CeirError(`ALTCHA failed after 3 attempts: ${lastError}`, 502, "ALTCHA_FAILED");
}

export async function withCeirSession<T>(work: (session: { page: Page; fetch: typeof bridgeFetch; altcha: () => Promise<string> }) => Promise<T>): Promise<T> {
  let release!: () => void;
  const previous = state.queue;
  state.queue = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  try {
    const page = await getReadyPage();
    return await work({ page, fetch: bridgeFetch, altcha: () => getAltchaToken(page) });
  } finally {
    release();
  }
}

export async function ceirHealth(forceReload = false) {
  let release!: () => void;
  const previous = state.queue;
  state.queue = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  const startedAt = Date.now();
  try {
    const page = await getReadyPage(forceReload);
    await getAltchaToken(page);
    return { ok: true, status: 200, latencyMs: Date.now() - startedAt };
  } finally {
    release();
  }
}

export function ceirJsonError(error: unknown): Response {
  const value = error instanceof CeirError ? error : new CeirError(error instanceof Error ? error.message : "Unexpected CEIR worker error");
  return Response.json({ ok: false, error: value.message, code: value.code }, { status: value.status });
}
