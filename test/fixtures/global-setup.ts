import { request } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";
const DEADLINE_MS = Number(process.env.HEALTH_TIMEOUT_MS ?? 120_000);

/**
 * Fail fast and loudly if the app under test is not up, rather than letting
 * every spec time out on a blank page and produce 40 identical red herrings.
 *
 * Also asserts the environment the suite is specified against: simulator market
 * data. Running the suite against live Massive data would make every price
 * assertion a coin flip.
 */
export default async function globalSetup() {
  const api = await request.newContext({ baseURL: BASE_URL });
  const startedAt = Date.now();
  let lastError = "never got a response";

  while (Date.now() - startedAt < DEADLINE_MS) {
    try {
      const res = await api.get("/api/health", { timeout: 5_000 });
      if (res.ok()) {
        const body = await res.json();
        console.log(`[global-setup] ${BASE_URL} healthy: ${JSON.stringify(body)}`);

        if (body.market_source !== "simulator") {
          throw new Error(
            `Refusing to run: market_source is "${body.market_source}", expected "simulator". ` +
              `Start the app under test with MASSIVE_API_KEY empty.`,
          );
        }

        const index = await api.get("/", { timeout: 10_000 });
        if (!index.ok()) {
          throw new Error(
            `Refusing to run: GET / returned ${index.status()}. The backend is not serving ` +
              `the frontend export. Set FINALLY_STATIC_DIR to frontend/out (or use the image).`,
          );
        }

        await api.dispose();
        return;
      }
      lastError = `HTTP ${res.status()}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }

  await api.dispose();
  throw new Error(
    `App under test never became healthy at ${BASE_URL} within ${DEADLINE_MS}ms. ` +
      `Last error: ${lastError}`,
  );
}
