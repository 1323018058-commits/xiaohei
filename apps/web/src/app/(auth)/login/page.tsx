"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/generated/api-types";

type LoginResponse = components["schemas"]["LoginResponse"];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });

      const data = (await response.json()) as LoginResponse | { detail?: string };
      if (!response.ok) {
        setErrorMessage("detail" in data ? data.detail ?? "登录失败" : "登录失败");
        return;
      }

      router.push("/dashboard");
      router.refresh();
    } catch {
      setErrorMessage("当前无法连接后端，请先启动 API 服务。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#FAFAFA] px-6 text-[#000000]">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-[360px] rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-6"
      >
        <div className="mb-6">
          <div className="text-xs font-medium text-[#595959]">Xiao Hei ERP</div>
          <h1 className="mt-2 text-[24px] font-semibold tracking-[-0.03em] text-[#000000]">
            登录小黑 ERP
          </h1>
          <p className="mt-2 text-sm leading-6 text-[#595959]">
            默认开发账号：admin / admin123
          </p>
        </div>

        <div className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-[#000000]">用户名</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="username"
              className="mt-2 h-10 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#595959] focus:border-[#000000]"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-[#000000]">密码</span>
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="password"
              type="password"
              className="mt-2 h-10 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#595959] focus:border-[#000000]"
            />
          </label>
        </div>

        {errorMessage ? (
          <div className="mt-4 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2 text-sm text-[#D9363E]">
            {errorMessage}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-[6px] border border-[#000000] bg-[#000000] px-4 text-sm font-medium text-[#FFFFFF] disabled:cursor-not-allowed disabled:opacity-35"
        >
          {isSubmitting ? "登录中..." : "登录"}
        </button>
      </form>
    </main>
  );
}
