import { redirect } from "next/navigation";

export default function Home() {
  // Hebrew/RTL-first default.
  redirect("/he");
}
