"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import type { components } from "@/generated/api-types";
import { formatApiErrorDetail } from "@/lib/api";

type LoginResponse = components["schemas"]["LoginResponse"];
type SendCodeResponse = {
  success: boolean;
  phone: string;
  expires_at: string;
  debug_code?: string | null;
};

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [companyName, setCompanyName] = useState("");
  const [loginAccount, setLoginAccount] = useState("admin");
  const [phone, setPhone] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [password, setPassword] = useState("admin123");
  const [codeMessage, setCodeMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [sendCooldown, setSendCooldown] = useState(0);

  useEffect(() => {
    if (sendCooldown <= 0) return;
    const timer = window.setTimeout(() => setSendCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [sendCooldown]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");

    const validationError = validateForm(mode, {
      companyName,
      loginAccount,
      phone,
      verificationCode,
      password,
    });
    if (validationError) {
      setErrorMessage(validationError);
      setIsSubmitting(false);
      return;
    }

    const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
    const body =
      mode === "login"
        ? { username: loginAccount, password }
        : {
            company_name: companyName,
            phone,
            verification_code: verificationCode,
            password,
          };

    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });

      const data = (await response.json()) as LoginResponse | { detail?: unknown };
      if (!response.ok) {
        setErrorMessage(formatApiErrorDetail("detail" in data ? data.detail : null, "操作失败"));
        return;
      }

      const nextPath =
        "session" in data && data.session.subscription_status === "unactivated"
          ? "/activate"
          : "/dashboard";
      router.push(nextPath);
      router.refresh();
    } catch {
      setErrorMessage("当前无法连接后端，请先确认 API 服务正在运行。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSendCode() {
    if (isSendingCode || sendCooldown > 0) return;
    setErrorMessage("");
    setCodeMessage("");
    const normalizedPhone = normalizePhone(phone);
    if (!isValidPhone(normalizedPhone)) {
      setErrorMessage("请输入正确的手机号。");
      return;
    }

    setIsSendingCode(true);
    try {
      const response = await fetch("/api/auth/register/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ phone }),
      });
      const data = (await response.json()) as SendCodeResponse | { detail?: unknown };
      if (!response.ok) {
        setErrorMessage(formatApiErrorDetail("detail" in data ? data.detail : null, "验证码发送失败"));
        return;
      }

      const sentCode = data as SendCodeResponse;
      setPhone(sentCode.phone || normalizedPhone);
      setCodeMessage(
        sentCode.debug_code
          ? `本地测试验证码：${sentCode.debug_code}`
          : "验证码已发送，请注意查收短信。",
      );
      setSendCooldown(60);
    } catch {
      setErrorMessage("验证码发送失败，请稍后重试。");
    } finally {
      setIsSendingCode(false);
    }
  }

  function switchMode(nextMode: Mode) {
    setMode(nextMode);
    setErrorMessage("");
    setCodeMessage("");
    setSendCooldown(0);
    if (nextMode === "register") {
      setPassword("");
    } else {
      setLoginAccount("admin");
      setPassword("admin123");
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#FAFAFA] px-6 text-[#000000]">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-[410px] rounded-[6px] border border-[#000000] bg-[#FFFFFF] p-6 shadow-[4px_4px_0_#000000]"
      >
        <div className="mb-6">
          <div className="text-xs font-black uppercase text-[#595959]">Xiao Hei ERP</div>
          <h1 className="mt-2 text-[24px] font-black text-[#000000]">
            {mode === "login" ? "登录小黑 ERP" : "手机号注册"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[#595959]">
            {mode === "login"
              ? "登录后继续管理 Takealot 运营数据。"
              : "手机号就是以后登录账号。注册后输入天卡激活使用权限。"}
          </p>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] p-1">
          <button
            type="button"
            onClick={() => switchMode("login")}
            className={`h-9 rounded-[4px] text-sm font-bold ${
              mode === "login" ? "border border-[#000000] bg-[#FFFFFF]" : "text-[#595959]"
            }`}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => switchMode("register")}
            className={`h-9 rounded-[4px] text-sm font-bold ${
              mode === "register" ? "border border-[#000000] bg-[#FFFFFF]" : "text-[#595959]"
            }`}
          >
            注册
          </button>
        </div>

        <div className="space-y-4">
          {mode === "register" ? (
            <>
              <label className="block">
                <span className="text-sm font-bold text-[#000000]">公司名称</span>
                <input
                  value={companyName}
                  onChange={(event) => setCompanyName(event.target.value)}
                  placeholder="请输入公司或团队名称"
                  className="mt-2 h-10 w-full rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#8C8C8C] focus:border-[#000000]"
                />
              </label>

              <label className="block">
                <span className="text-sm font-bold text-[#000000]">手机号</span>
                <div className="mt-2 grid grid-cols-[minmax(0,1fr)_116px] gap-2">
                  <input
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                    placeholder="13800138000"
                    inputMode="tel"
                    className="h-10 w-full rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#8C8C8C] focus:border-[#000000]"
                  />
                  <button
                    type="button"
                    onClick={() => void handleSendCode()}
                    disabled={isSendingCode || sendCooldown > 0}
                    className="h-10 rounded-[4px] border border-[#000000] bg-[#FFFFFF] px-3 text-xs font-black text-[#000000] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {isSendingCode ? "发送中" : sendCooldown > 0 ? `${sendCooldown}s` : "发送验证码"}
                  </button>
                </div>
              </label>

              <label className="block">
                <span className="text-sm font-bold text-[#000000]">验证码</span>
                <input
                  value={verificationCode}
                  onChange={(event) => setVerificationCode(event.target.value)}
                  placeholder="6 位验证码"
                  inputMode="numeric"
                  className="mt-2 h-10 w-full rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#8C8C8C] focus:border-[#000000]"
                />
              </label>
            </>
          ) : (
            <label className="block">
              <span className="text-sm font-bold text-[#000000]">手机号 / 管理员账号</span>
              <input
                value={loginAccount}
                onChange={(event) => setLoginAccount(event.target.value)}
                placeholder="手机号"
                className="mt-2 h-10 w-full rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#8C8C8C] focus:border-[#000000]"
              />
            </label>
          )}

          <label className="block">
            <span className="text-sm font-bold text-[#000000]">密码</span>
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "register" ? "至少 8 位" : "password"}
              type="password"
              className="mt-2 h-10 w-full rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#8C8C8C] focus:border-[#000000]"
            />
          </label>
        </div>

        {codeMessage ? (
          <div className="mt-4 rounded-[4px] border border-[#15803D] bg-[#F0FDF4] px-3 py-2 text-sm text-[#166534]">
            {codeMessage}
          </div>
        ) : null}

        {errorMessage ? (
          <div className="mt-4 rounded-[4px] border border-[#DC2626] bg-[#FEF2F2] px-3 py-2 text-sm text-[#B91C1C]">
            {errorMessage}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-[4px] border border-[#000000] bg-[#000000] px-4 text-sm font-black text-[#FFFFFF] disabled:cursor-not-allowed disabled:opacity-35"
        >
          {isSubmitting ? "处理中..." : mode === "login" ? "登录" : "注册账号"}
        </button>
      </form>
    </main>
  );
}

function validateForm(
  mode: Mode,
  form: {
    companyName: string;
    loginAccount: string;
    phone: string;
    verificationCode: string;
    password: string;
  },
) {
  const password = form.password.trim();
  if (mode === "register") {
    if (form.companyName.trim().length < 2) return "公司名称至少 2 个字。";
    if (!isValidPhone(normalizePhone(form.phone))) return "请输入正确的手机号。";
    if (!/^\d{4,12}$/.test(form.verificationCode.trim())) return "请输入正确的验证码。";
    if (password.length < 8) return "密码至少 8 位。";
    return "";
  }

  if (!form.loginAccount.trim()) return "请输入手机号或管理员账号。";
  if (!password) return "请输入密码。";
  return "";
}

function normalizePhone(value: string) {
  const compact = value.trim().replace(/[\s\-().]/g, "");
  if (compact.startsWith("00")) {
    return `+${compact.slice(2)}`;
  }
  return compact;
}

function isValidPhone(value: string) {
  return /^\+?\d{8,16}$/.test(value);
}
