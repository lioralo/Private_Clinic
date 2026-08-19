import { defineConfig, devices } from "@playwright/test";

const nextBaseURL = "http://localhost:3000";
const nextAuthSecret = "dev-nextauth-secret-change-me";

export default defineConfig({
  testDir: "./e2e",
  retries: 0,
  timeout: 60_000,

  use: {
    baseURL: nextBaseURL,
    trace: "on-first-retry",
    ...devices["Desktop Chrome"],
  },

  webServer: {
    command:
      'sh -c "npm run db:migrate && npm run db:seed && NEXTAUTH_URL=http://localhost:3000 NEXTAUTH_SECRET=' +
      nextAuthSecret +
      ' ADMIN_USERNAME=admin ADMIN_PASSWORD=admin-password DATABASE_URL=file:./dev.db PORT=3000 NEXT_DISABLE_TURBOPACK=1 npm run dev"',
    url: nextBaseURL,
    reuseExisting: false,
    timeout: 180_000,
  },
});

