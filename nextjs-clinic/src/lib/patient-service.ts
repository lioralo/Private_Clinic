import { prisma } from "./prisma";

export async function listPatients() {
  return prisma.patient.findMany({
    orderBy: { createdAt: "desc" },
    take: 100,
  });
}

export async function createPatient(data: {
  firstName: string;
  lastName: string;
  phone?: string | null;
  email?: string | null;
  notesText?: string | null;
}) {
  return prisma.patient.create({
    data: {
      firstName: data.firstName,
      lastName: data.lastName,
      phone: data.phone ?? null,
      email: data.email ?? null,
      notesText: data.notesText ?? null,
    },
  });
}

