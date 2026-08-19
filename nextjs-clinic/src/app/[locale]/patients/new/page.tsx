import { redirect } from "next/navigation";

import { prisma } from "@/lib/prisma";

export default function NewPatientPage({
  params,
}: {
  params: { locale: "en" | "he" };
}) {
  async function createPatient(formData: FormData) {
    "use server";

    const firstName = String(formData.get("firstName") ?? "").trim();
    const lastName = String(formData.get("lastName") ?? "").trim();
    const phone = String(formData.get("phone") ?? "").trim() || null;
    const email = String(formData.get("email") ?? "").trim() || null;
    const notesText =
      String(formData.get("notesText") ?? "").trim() || null;

    if (!firstName || !lastName) {
      // For MVP, redirect back. Real apps should surface validation errors.
      redirect(`/${params.locale}/patients/new`);
    }

    await prisma.patient.create({
      data: {
        firstName,
        lastName,
        phone,
        email,
        notesText,
      },
    });

    redirect(`/${params.locale}/patients`);
  }

  return (
    <div className="max-w-3xl">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold mb-1">
          {params.locale === "he" ? "מטופל חדש" : "New patient"}
        </h1>
        <p className="text-[var(--color-foreground)]/70">
          {params.locale === "he"
            ? "יצירת רשומת מטופל בסיסית"
            : "Create a basic patient record."}
        </p>
      </div>

      <form
        action={createPatient}
        className="rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] p-5 flex flex-col gap-4"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            {params.locale === "he" ? "שם פרטי" : "First name"}
            <input
              name="firstName"
              className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
              required
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {params.locale === "he" ? "שם משפחה" : "Last name"}
            <input
              name="lastName"
              className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
              required
            />
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            {params.locale === "he" ? "טלפון" : "Phone"}
            <input
              name="phone"
              className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {params.locale === "he" ? "אימייל" : "Email"}
            <input
              name="email"
              type="email"
              className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
            />
          </label>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          {params.locale === "he" ? "הערות" : "Notes"}
          <textarea
            name="notesText"
            className="min-h-28 rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
          />
        </label>

        <div className="flex gap-3">
          <button
            type="submit"
            className="rounded-xl bg-[var(--color-primary)] text-[var(--color-surface)] py-2 px-4 font-semibold hover:opacity-90"
          >
            {params.locale === "he" ? "שמור" : "Save"}
          </button>

          <a
            href={`/${params.locale}/patients`}
            className="rounded-xl border border-[var(--color-border)] px-4 py-2"
          >
            {params.locale === "he" ? "ביטול" : "Cancel"}
          </a>
        </div>
      </form>
    </div>
  );
}

