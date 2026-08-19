import { PrismaClient } from "@prisma/client";
import { PrismaSqlite } from "prisma-adapter-sqlite";

// Prevent creating many PrismaClient instances in dev (Next.js hot reload).
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  throw new Error(
    "Missing DATABASE_URL. Set it in your environment (e.g. file:./dev.db)."
  );
}

const adapter = new PrismaSqlite({ connectionString: databaseUrl });

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    adapter,
    log:
      process.env.NODE_ENV === "development" ? ["error", "warn"] : ["error"],
  });

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}

