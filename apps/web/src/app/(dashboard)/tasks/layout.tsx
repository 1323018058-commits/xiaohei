import { requireServerRoles } from "@/lib/server-session";

export default async function TasksLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireServerRoles(["super_admin", "tenant_admin"]);
  return children;
}
