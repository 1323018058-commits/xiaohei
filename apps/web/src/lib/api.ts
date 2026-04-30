export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  const text = await response.text();
  let data: (T & { detail?: string }) | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as T & { detail?: string };
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, data?.detail ?? (text || "Request failed"));
  }

  return data as T;
}
