import {getRequestConfig} from "next-intl/server";

import {defaultLocale, locales, type Locale} from "./routing";

export default getRequestConfig(async ({locale}) => {
  const resolvedLocale = (locales as readonly string[]).includes(locale)
    ? (locale as Locale)
    : defaultLocale;

  return {
    messages: (await import(`../messages/${resolvedLocale}.json`)).default,
  };
});

