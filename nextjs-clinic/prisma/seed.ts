import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma";

async function main() {
  const username = process.env.ADMIN_USERNAME ?? "admin";
  const password = process.env.ADMIN_PASSWORD ?? "admin-password";

  const existing = await prisma.user.findUnique({
    where: { username },
  });

  if (existing) {
    return;
  }

  const passwordHash = await bcrypt.hash(password, 12);

  await prisma.user.create({
    data: {
      username,
      passwordHash,
      role: "ADMIN",
    },
  });
}

main()
  .catch((e) => {
    // eslint-disable-next-line no-console
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

