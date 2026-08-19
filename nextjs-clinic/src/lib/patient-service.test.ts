import { describe, expect, it, vi } from "vitest";

vi.mock("./prisma", () => {
  return {
    prisma: {
      patient: {
        findMany: vi.fn(),
        create: vi.fn(),
      },
    },
  };
});

import { prisma } from "./prisma";
import { createPatient, listPatients } from "./patient-service";

describe("patient-service (CRUD wrappers)", () => {
  it("listPatients calls prisma.patient.findMany with ordering", async () => {
    (prisma.patient.findMany as any).mockResolvedValue([{ id: "p1" }]);

    const result = await listPatients();

    expect(prisma.patient.findMany).toHaveBeenCalledWith({
      orderBy: { createdAt: "desc" },
      take: 100,
    });
    expect(result).toEqual([{ id: "p1" }]);
  });

  it("createPatient calls prisma.patient.create with mapped fields", async () => {
    (prisma.patient.create as any).mockResolvedValue({ id: "p2" });

    await createPatient({
      firstName: "A",
      lastName: "B",
      phone: "050",
      email: null,
      notesText: "hi",
    });

    expect(prisma.patient.create).toHaveBeenCalledWith({
      data: {
        firstName: "A",
        lastName: "B",
        phone: "050",
        email: null,
        notesText: "hi",
      },
    });
  });
});

