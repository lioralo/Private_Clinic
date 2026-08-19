import { prisma } from "@/lib/prisma";

function toInputValue(d: Date) {
  // yyyy-MM-ddThh:mm for <input type="datetime-local" />
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate()
  )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default async function CalendarPage({
  params,
}: {
  params: { locale: "en" | "he" };
}) {
  const patients = await prisma.patient.findMany({
    orderBy: { createdAt: "desc" },
    take: 200,
  });

  const appointments = await prisma.appointment.findMany({
    where: { startAt: { gte: new Date() } },
    orderBy: { startAt: "asc" },
    take: 50,
    include: { patient: true },
  });

  async function createAppointment(formData: FormData) {
    "use server";

    const patientId = String(formData.get("patientId") ?? "");
    const startAtRaw = String(formData.get("startAt") ?? "");
    const endAtRaw = String(formData.get("endAt") ?? "");

    if (!patientId || !startAtRaw || !endAtRaw) {
      return;
    }

    const provider =
      (await prisma.user.findFirst({ where: { role: "ADMIN" } })) ??
      (await prisma.user.findFirst());

    if (!provider) return;

    const startAt = new Date(startAtRaw);
    const endAt = new Date(endAtRaw);

    await prisma.appointment.create({
      data: {
        patientId,
        providerId: provider.id,
        startAt,
        endAt,
      },
    });

    // After submission, revalidate by redirecting back.
    // (In Next.js, server actions + forms will refresh the route.)
  }

  const now = new Date();
  const defaultStart = new Date(now.getTime() + 60 * 60 * 1000);
  const defaultEnd = new Date(now.getTime() + 2 * 60 * 60 * 1000);

  return (
    <div className="max-w-5xl">
      <h1 className="text-2xl font-semibold mb-3">
        {params.locale === "he" ? "יומן" : "Calendar"}
      </h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <div className="rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold">
                {params.locale === "he" ? "פגישות קרובות" : "Upcoming"}
              </div>
              <div className="text-sm text-[var(--color-foreground)]/70">
                {appointments.length}
              </div>
            </div>
            {appointments.length === 0 ? (
              <div className="text-[var(--color-foreground)]/70">
                {params.locale === "he"
                  ? "אין פגישות קרובות."
                  : "No upcoming appointments."}
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {appointments.map((a) => (
                  <li
                    key={a.id}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-primary-container)]/30 p-3"
                  >
                    <div className="font-medium">
                      {a.patient.firstName} {a.patient.lastName}
                    </div>
                    <div className="text-sm text-[var(--color-foreground)]/70">
                      {a.startAt.toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div>
          <div className="rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] p-4">
            <div className="font-semibold mb-3">
              {params.locale === "he" ? "הוספת פגישה" : "Add appointment"}
            </div>

            <form action={createAppointment} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                {params.locale === "he" ? "מטופל" : "Patient"}
                <select
                  name="patientId"
                  className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
                  defaultValue={patients[0]?.id ?? ""}
                >
                  {patients.length === 0 ? (
                    <option value="" disabled>
                      {params.locale === "he"
                        ? "אין מטופלים"
                        : "No patients"}
                    </option>
                  ) : (
                    patients.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.firstName} {p.lastName}
                      </option>
                    ))
                  )}
                </select>
              </label>

              <label className="flex flex-col gap-1 text-sm">
                {params.locale === "he" ? "תחילה" : "Start"}
                <input
                  type="datetime-local"
                  name="startAt"
                  defaultValue={toInputValue(defaultStart)}
                  className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                {params.locale === "he" ? "סיום" : "End"}
                <input
                  type="datetime-local"
                  name="endAt"
                  defaultValue={toInputValue(defaultEnd)}
                  className="rounded-xl border border-[var(--color-border)] bg-transparent px-3 py-2 outline-none"
                />
              </label>

              <button
                type="submit"
                disabled={patients.length === 0}
                className="rounded-xl bg-[var(--color-primary)] text-[var(--color-surface)] py-2 px-3 font-semibold hover:opacity-90 disabled:opacity-60"
              >
                {params.locale === "he" ? "שמור פגישה" : "Save appointment"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

