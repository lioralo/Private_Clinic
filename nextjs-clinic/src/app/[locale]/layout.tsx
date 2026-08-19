import React from "react";
import { notFound } from "next/navigation";
import AppShell from "@/components/app-shell";
import {NextIntlClientProvider} from "next-intl";
import {getMessages} from "next-intl/server";
import SessionProviderWrapper from "@/components/session-provider";

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  // Next 16 may pass params as a Promise in async server components.
  params: Promise<{ locale: string }> | { locale: string };
}) {
  const resolvedParams = await params;

  const locale =
    resolvedParams.locale === "he"
      ? "he"
      : resolvedParams.locale === "en"
        ? "en"
        : null;
  if (!locale) notFound();

  const dir = locale === "he" ? "rtl" : "ltr";
  const messages = await getMessages();

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <SessionProviderWrapper>
        <div dir={dir} lang={locale}>
          <AppShell locale={locale}>{children}</AppShell>
        </div>
      </SessionProviderWrapper>
    </NextIntlClientProvider>
  );
}

