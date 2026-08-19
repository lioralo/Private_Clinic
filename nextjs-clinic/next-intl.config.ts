import type { NextIntlConfig } from "next-intl";

// next-intl expects this config entrypoint for App Router.
const config: NextIntlConfig = {
  locales: ["en", "he"],
  defaultLocale: "he",
  localePrefix: "always",
};

export default config;

