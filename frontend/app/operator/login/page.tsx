import { redirect } from "next/navigation";

export default function OperatorLoginPage() {
  redirect("/access?next=/operator");
}
