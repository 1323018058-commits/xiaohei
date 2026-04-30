"use client";

import { useRouter } from "next/navigation";
import { useState, type CSSProperties, type FormEvent } from "react";

import { ApiError, apiFetch } from "@/lib/api";

type RedeemResponse = {
  success: boolean;
  tenant_id: string;
  plan: string;
  subscription_status: string;
  current_period_ends_at: string;
  added_days: number;
};

export function ActivationPanel({
  username,
  subscriptionStatus,
}: {
  username: string;
  subscriptionStatus: string;
}) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setMessage("");
    setErrorMessage("");

    try {
      const result = await apiFetch<RedeemResponse>("/api/subscription/redeem-card", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setMessage(`已激活 ${result.added_days} 天，有效期至 ${formatDate(result.current_period_ends_at)}。`);
      setCode("");
      router.refresh();
      window.setTimeout(() => router.push("/dashboard"), 600);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 404) {
          setErrorMessage("天卡不存在，请检查后重新输入。");
        } else if (error.status === 409) {
          setErrorMessage("这张天卡已经被使用或已作废。");
        } else {
          setErrorMessage(error.detail || "激活失败。");
        }
      } else {
        setErrorMessage("当前无法连接后端，请稍后再试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main style={pageStyle}>
      <section style={panelStyle}>
        <div style={eyebrowStyle}>Xiao Hei ERP</div>
        <h1 style={titleStyle}>激活账号</h1>
        <p style={copyStyle}>
          {username} 当前状态为 {formatStatus(subscriptionStatus)}。请输入管理员发放的天卡，激活后即可进入 ERP。
        </p>

        <form onSubmit={handleSubmit} style={formStyle}>
          <label style={fieldStyle}>
            <span style={labelStyle}>天卡</span>
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="XH-XXXX-XXXX-XXXX-XXXX"
              style={inputStyle}
              autoComplete="off"
            />
          </label>

          {message ? <div style={successStyle}>{message}</div> : null}
          {errorMessage ? <div style={errorStyle}>{errorMessage}</div> : null}

          <button type="submit" disabled={isSubmitting || !code.trim()} style={buttonStyle}>
            {isSubmitting ? "激活中..." : "激活并进入 ERP"}
          </button>
        </form>
      </section>
    </main>
  );
}

function formatStatus(status: string) {
  if (status === "unactivated") return "未激活";
  if (status === "past_due") return "已到期";
  if (status === "active") return "正常";
  return status || "--";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

const pageStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: 24,
  background: "#FAFAFA",
  color: "#000000",
};

const panelStyle: CSSProperties = {
  width: "min(440px, 100%)",
  border: "1px solid #000000",
  borderRadius: 6,
  background: "#FFFFFF",
  padding: 24,
  boxShadow: "4px 4px 0 #000000",
};

const eyebrowStyle: CSSProperties = {
  fontSize: 11,
  fontWeight: 800,
  color: "#595959",
  textTransform: "uppercase",
};

const titleStyle: CSSProperties = {
  margin: "8px 0 0",
  fontSize: 26,
  lineHeight: 1.1,
  fontWeight: 900,
  letterSpacing: 0,
};

const copyStyle: CSSProperties = {
  margin: "12px 0 0",
  fontSize: 14,
  lineHeight: 1.7,
  color: "#595959",
};

const formStyle: CSSProperties = {
  marginTop: 22,
  display: "grid",
  gap: 14,
};

const fieldStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const labelStyle: CSSProperties = {
  fontSize: 13,
  fontWeight: 760,
};

const inputStyle: CSSProperties = {
  height: 42,
  border: "1px solid #000000",
  borderRadius: 4,
  padding: "0 12px",
  fontSize: 14,
  outline: "none",
  background: "#FFFFFF",
};

const buttonStyle: CSSProperties = {
  height: 42,
  border: "1px solid #000000",
  borderRadius: 4,
  background: "#000000",
  color: "#FFFFFF",
  fontSize: 14,
  fontWeight: 850,
  cursor: "pointer",
};

const successStyle: CSSProperties = {
  border: "1px solid #15803D",
  borderRadius: 4,
  padding: "9px 10px",
  background: "#F0FDF4",
  color: "#166534",
  fontSize: 13,
};

const errorStyle: CSSProperties = {
  border: "1px solid #DC2626",
  borderRadius: 4,
  padding: "9px 10px",
  background: "#FEF2F2",
  color: "#B91C1C",
  fontSize: 13,
};
