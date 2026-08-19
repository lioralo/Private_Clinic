import Link from "next/link";
import { notFound } from "next/navigation";

import { prisma } from "@/lib/prisma";

export default async function PatientDetailPage({
  params,
}: {
  params: { locale: "en" | "he"; id: string };
}) {
  const patient = await prisma.patient.findUnique({
    where: { id: params.id },
  });

  if (!patient) notFound();

  return (
    <div className="max-w-3xl">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold mb-1">
            {patient.firstName} {patient.lastName}
          </h1>
          <p className="text-[var(--color-foreground)]/70">
            {params.locale === "he" ? "פרטי מטופל" : "Patient details"}
          </p>
        </div>

        <Link
          href={`/${params.locale}/patients`}
          className="rounded-xl border border-[var(--color-border)] px-4 py-2"
        >
          {params.locale === "he" ? "חזרה" : "Back"}
        </Link>
      </div>

      <div className="rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] p-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="text-sm text-[var(--color-foreground)]/70">
              {params.locale === "he" ? "טלפון" : "Phone"}
            </div>
            <div className="font-medium">{patient.phone ?? "—"}</div>
          </div>
          <div>
            <div className="text-sm text-[var(--color-foreground)]/70">
              {params.locale === "he" ? "אימייל" : "Email"}
            </div>
            <div className="font-medium">{patient.email ?? "—"}</div>
          </div>
        </div>

        <div className="mt-5">
          <div className="text-sm text-[var(--color-foreground)]/70">
            {params.locale === "he" ? "הערות" : "Notes"}
          </div>
          <div className="mt-1 whitespace-pre-wrap">
            {patient.notesText ?? "—"}
          </div>
        </div>
      </div>
    </div>
  );
}

