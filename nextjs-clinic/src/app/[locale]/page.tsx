import { prisma } from "@/lib/prisma";

export default async function DashboardPage({
  params,
}: {
  params: { locale: "en" | "he" };
}) {
  const patientCount = await prisma.patient.count();
  const upcoming = await prisma.appointment.findMany({
    where: { startAt: { gte: new Date() } },
    orderBy: { startAt: "asc" },
    take: 5,
    include: { patient: true },
  });

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold mb-2">
        {params.locale === "he" ? "דשבורד" : "Dashboard"}
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] p-5">
          <div className="text-sm text-[var(--color-foreground)]/70">
            {params.locale === "he" ? "סך הכל מטופלים" : "Total patients"}
          </div>
          <div className="text-3xl font-semibold">{patientCount}</div>
        </div>

        <div className="rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] p-5">
          <div className="text-sm text-[var(--color-foreground)]/70">
            {params.locale === "he" ? "פגישות קרובות" : "Upcoming appointments"}
          </div>
          <div className="text-3xl font-semibold">{upcoming.length}</div>
        </div>
      </div>

      <div className="mt-5 rounded-2xl border bg-[var(--color-surface)] border-[var(--color-border)] p-5">
        <div className="text-lg font-semibold mb-3">
          {params.locale === "he" ? "רשימת פגישות" : "Appointments"}
        </div>
        {upcoming.length === 0 ? (
          <div className="text-[var(--color-foreground)]/70">
            {params.locale === "he"
              ? "אין פגישות קרובות."
              : "No upcoming appointments."}
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {upcoming.map((a) => (
              <li
                key={a.id}
                className="rounded-xl bg-[var(--color-primary-container)]/40 border border-[var(--color-border)] p-3"
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
  );
}

