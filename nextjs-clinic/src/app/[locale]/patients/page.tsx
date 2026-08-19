import Link from "next/link";

import { prisma } from "@/lib/prisma";

export default async function PatientsPage({
  params,
}: {
  params: Promise<{ locale: "en" | "he" }> | { locale: "en" | "he" };
}) {
  const resolvedParams = await params;
  const locale = resolvedParams.locale;

  const patients = await prisma.patient.findMany({
    orderBy: { createdAt: "desc" },
    take: 100,
  });

  return (
    <div className="max-w-5xl">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-semibold mb-1">
            {locale === "he" ? "מטופלים" : "Patients"}
          </h1>
          <p className="text-[var(--color-foreground)]/70">
            {locale === "he"
              ? "רשימת מטופלים"
              : "Patient list (CRUD in v1 starter)."}
          </p>
        </div>

        <Link
          href={`/${locale}/patients/new`}
          className="rounded-xl bg-[var(--color-primary)] text-[var(--color-surface)] px-4 py-2 font-semibold hover:opacity-90"
        >
          {locale === "he" ? "מטופל חדש" : "New patient"}
        </Link>
      </div>

      <div className="rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--color-primary-container)]/40">
              <th className="text-start px-4 py-3 font-semibold">
                {locale === "he" ? "שם" : "Name"}
              </th>
              <th className="text-start px-4 py-3 font-semibold">
                {locale === "he" ? "טלפון" : "Phone"}
              </th>
              <th className="text-start px-4 py-3 font-semibold">
                {locale === "he" ? "אימייל" : "Email"}
              </th>
              <th className="text-end px-4 py-3 font-semibold">
                {locale === "he" ? "פעולות" : "Actions"}
              </th>
            </tr>
          </thead>
          <tbody>
            {patients.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-[var(--color-foreground)]/70">
                  {locale === "he"
                    ? "אין עדיין מטופלים."
                    : "No patients yet."}
                </td>
              </tr>
            ) : (
              patients.map((p) => (
                <tr key={p.id} className="border-t border-[var(--color-border)]">
                  <td className="px-4 py-3 font-medium">
                    <Link
                      className="hover:underline"
                      href={`/${locale}/patients/${p.id}`}
                    >
                      {p.firstName} {p.lastName}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{p.phone ?? "—"}</td>
                  <td className="px-4 py-3">{p.email ?? "—"}</td>
                  <td className="px-4 py-3 text-end">
                    <Link
                      className="text-[var(--color-primary-dark)] hover:underline"
                      href={`/${locale}/patients/${p.id}`}
                    >
                      {locale === "he" ? "צפה" : "View"}
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

