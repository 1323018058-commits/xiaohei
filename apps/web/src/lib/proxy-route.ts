import type { NextRequest } from "next/server";

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

function createUpstreamUrl(prefix: string, requestUrl: string, path: string[]) {
  const incomingUrl = new URL(requestUrl);
  const upstreamUrl = new URL(`${apiProxyTarget}${prefix}/${path.join("/")}`);
  upstreamUrl.search = incomingUrl.search;
  return upstreamUrl;
}

async function createUpstreamInit(request: NextRequest): Promise<RequestInit> {
  const headers = new Headers();
  const acceptedHeaders = ["accept", "authorization", "content-type", "cookie"];

  acceptedHeaders.forEach((headerName) => {
    const headerValue = request.headers.get(headerName);
    if (headerValue) {
      headers.set(headerName, headerValue);
    }
  });

  const method = request.method.toUpperCase();
  if (method === "GET" || method === "HEAD") {
    return {
      method,
      headers,
      cache: "no-store",
      redirect: "manual",
    };
  }

  const body = await request.arrayBuffer();
  if (body.byteLength === 0) {
    return {
      method,
      headers,
      cache: "no-store",
      redirect: "manual",
    };
  }

  return {
    method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  };
}

export async function proxyRoute(request: NextRequest, prefix: string, path: string[]) {
  const upstreamResponse = await fetch(createUpstreamUrl(prefix, request.url, path), await createUpstreamInit(request));
  const responseHeaders = new Headers();
  const contentType = upstreamResponse.headers.get("content-type");
  const cacheControl = upstreamResponse.headers.get("cache-control");
  const location = upstreamResponse.headers.get("location");
  const setCookie = upstreamResponse.headers.get("set-cookie");

  if (contentType) {
    responseHeaders.set(
      "content-type",
      contentType.toLowerCase().startsWith("application/json") && !contentType.toLowerCase().includes("charset=")
        ? `${contentType}; charset=utf-8`
        : contentType,
    );
  }
  if (cacheControl) {
    responseHeaders.set("cache-control", cacheControl);
  }
  if (location) {
    responseHeaders.set("location", location);
  }
  if (setCookie) {
    responseHeaders.set("set-cookie", setCookie);
  }

  const responseBody = request.method.toUpperCase() === "HEAD" ? null : await upstreamResponse.arrayBuffer();
  return new Response(responseBody, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  });
}
