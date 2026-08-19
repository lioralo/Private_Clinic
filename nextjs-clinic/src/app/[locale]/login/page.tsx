"use client";

import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

export default function LoginPage({ params }: { params: { locale: "en" | "he" } }) {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin-password");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const res = await signIn("credentials", {
      username,
      password,
      redirect: false,
    });

    setSubmitting(false);

    if (!res?.ok) {
      setError(
        params.locale === "he"
          ? "פרטי התחברות לא נכונים."
          : "Invalid username or password."
      );
      return;
    }

    router.push(`/${params.locale}`);
  }

  return (
    <div className="max-w-md">
      <h1 className="text-2xl font-semibold mb-2">
        {params.locale === "he" ? "התחברות" : "Login"}
      </h1>
      <p className="text-[var(--color-foreground)]/70 mb-4">
        {params.locale === "he"
          ? "היכנס/י למערכת עם שם משתמש וסיסמה."
          : "Sign in with your username and password."}
      </p>

      <form
        onSubmit={onSubmit}
        className="rounded-2xl border p-4 border-[var(--color-border)] bg-[var(--color-surface)] flex flex-col gap-3"
      >
        <label className="flex flex-col gap-1 text-sm">
          {params.locale === "he" ? "שם משתמש" : "Username"}
          <input
            className="rounded-xl border px-3 py-2 border-[var(--color-border)] bg-transparent outline-none"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {params.locale === "he" ? "סיסמה" : "Password"}
          <input
            type="password"
            className="rounded-xl border px-3 py-2 border-[var(--color-border)] bg-transparent outline-none"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && (
          <div className="text-sm text-[var(--color-primary-dark)]">{error}</div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded-xl bg-[var(--color-primary)] text-[var(--color-surface)] py-2 px-3 font-semibold hover:opacity-90 disabled:opacity-60"
        >
          {submitting
            ? params.locale === "he"
              ? "מתחבר..."
              : "Signing in..."
            : params.locale === "he"
            ? "התחבר"
            : "Sign in"}
        </button>
      </form>
    </div>
  );
}

