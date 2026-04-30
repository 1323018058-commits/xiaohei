import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { components } from "@/generated/api-types";

type SessionInfoResponse = components["schemas"]["SessionInfoResponse"];

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const sessionCookieName = "erp_session";

export async function getServerSessionInfo(): Promise<SessionInfoResponse | null> {
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get(sessionCookieName)?.value;

  if (!sessionToken) {
    return null;
  }

  try {
    const response = await fetch(`${apiProxyTarget}/api/auth/me`, {
      method: "GET",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        Cookie: `${sessionCookieName}=${sessionToken}`,
      },
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as SessionInfoResponse;
  } catch {
    return null;
  }
}

export async function requireServerRoles(
  allowedRoles: string[],
  redirectTo = "/dashboard",
): Promise<SessionInfoResponse> {
  const session = await getServerSessionInfo();

  if (!session) {
    redirect("/login");
  }

  if (!allowedRoles.includes(session.user.role)) {
    redirect(redirectTo);
  }

  return session;
}
