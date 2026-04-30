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

export function formatApiErrorDetail(detail: unknown, fallback = "请求失败"): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => formatValidationIssue(item)).filter(Boolean);
    if (messages.length > 0) {
      return messages.join("；");
    }
  }

  if (isRecord(detail)) {
    const message = detail.message ?? detail.msg ?? detail.detail ?? detail.error;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }

  return fallback;
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
  let data: (T & { detail?: unknown }) | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as T & { detail?: unknown };
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, formatApiErrorDetail(data?.detail, text || "请求失败"));
  }

  return data as T;
}

function formatValidationIssue(value: unknown): string {
  if (typeof value === "string") return value;
  if (!isRecord(value)) return "";
  const rawMessage = typeof value.msg === "string" ? value.msg : "输入不符合要求";
  const field = validationFieldLabel(value.loc);
  return field ? `${field}${translateValidationMessage(rawMessage)}` : translateValidationMessage(rawMessage);
}

function validationFieldLabel(loc: unknown) {
  if (!Array.isArray(loc) || loc.length === 0) return "";
  const field = String(loc[loc.length - 1]);
  const labels: Record<string, string> = {
    company_name: "公司名称",
    username: "账号",
    phone: "手机号",
    verification_code: "验证码",
    email: "邮箱",
    password: "密码",
    code: "天卡",
    days: "天数",
    quantity: "数量",
  };
  return labels[field] ? `${labels[field]}：` : `${field}：`;
}

function translateValidationMessage(message: string) {
  if (/at least 8 characters/i.test(message) || /should have at least 8/i.test(message)) {
    return "至少 8 位";
  }
  if (/at least 3 characters/i.test(message) || /should have at least 3/i.test(message)) {
    return "至少 3 位";
  }
  if (/at least 2 characters/i.test(message) || /should have at least 2/i.test(message)) {
    return "至少 2 位";
  }
  if (/string should match pattern/i.test(message)) {
    return "只能使用英文字母、数字、下划线或中划线";
  }
  if (/valid email/i.test(message)) {
    return "格式不正确";
  }
  return message;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
