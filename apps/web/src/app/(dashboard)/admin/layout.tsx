import { requireServerRoles } from "@/lib/server-session";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireServerRoles(["super_admin", "tenant_admin"]);
  return children;
}
