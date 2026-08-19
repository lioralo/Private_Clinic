import { getToken } from "next-auth/jwt";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const protectedPrefixes = ["/patients", "/calendar"];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  const parts = pathname.split("/");
  const locale = parts[1];

  if (locale !== "he" && locale !== "en") {
    return NextResponse.next();
  }

  // Allow access to auth + Next.js internals.
  if (
    pathname === `/${locale}/login` ||
    pathname.startsWith(`/${locale}/login`) ||
    pathname.startsWith(`/${locale}/api/auth`) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon")
  ) {
    return NextResponse.next();
  }

  const isProtected =
    pathname === `/${locale}` ||
    protectedPrefixes.some((p) => pathname.startsWith(`/${locale}${p}`));

  if (!isProtected) return NextResponse.next();

  const token = await getToken({
    req,
    secret: process.env.NEXTAUTH_SECRET,
  });

  if (!token) {
    const loginUrl = new URL(`/${locale}/login`, req.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

