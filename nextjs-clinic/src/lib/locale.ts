export type AppLocale = "he" | "en";

export function normalizeLocale(locale: string | undefined): AppLocale | null {
  if (locale === "he") return "he";
  if (locale === "en") return "en";
  return null;
}

export function localeToDir(locale: AppLocale): "rtl" | "ltr" {
  return locale === "he" ? "rtl" : "ltr";
}

export function otherLocale(locale: AppLocale): AppLocale {
  return locale === "he" ? "en" : "he";
}

