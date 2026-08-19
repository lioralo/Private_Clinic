import React from "react";
import { notFound } from "next/navigation";
import AppShell from "@/components/app-shell";
import {NextIntlClientProvider} from "next-intl";
import {getMessages} from "next-intl/server";
import SessionProviderWrapper from "@/components/session-provider";

export default function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  // This layout is async via NextIntl's message loading below.
  // (Next.js allows an async function even if the type signature is simple.)
  return <LocaleLayoutInner children={children} params={params} />;
}

async function LocaleLayoutInner({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  const locale =
    params.locale === "he" ? "he" : params.locale === "en" ? "en" : null;
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

