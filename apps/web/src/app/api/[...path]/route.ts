import type { NextRequest } from "next/server";

import { proxyRoute } from "@/lib/proxy-route";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function handle(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxyRoute(request, "/api", path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
export const HEAD = handle;
