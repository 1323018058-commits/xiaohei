"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type DashboardContextResponse = components["schemas"]["DashboardContextResponse"];

export function DashboardStatusBadges({
  fallbackSubscriptionStatus,
}: {
  fallbackSubscriptionStatus: string;
}) {
  const [context, setContext] = useState<DashboardContextResponse | null>(null);
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadContext() {
      try {
        const data = await apiFetch<DashboardContextResponse>("/api/v1/dashboard/context");
        if (!isCancelled) {
          setContext(data);
        }
      } catch {
        if (!isCancelled) {
          setContext(null);
        }
      }
    }

    void loadContext();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const southAfricaTime = useMemo(
    () => {
      if (!now) return "--:--:--";
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: context?.business_timezone ?? "Africa/Johannesburg",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(now);
    },
    [now, context?.business_timezone],
  );

  const southAfricaDate = useMemo(
    () => {
      if (!now) return "--/--";
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: context?.business_timezone ?? "Africa/Johannesburg",
        month: "2-digit",
        day: "2-digit",
      }).format(now);
    },
    [now, context?.business_timezone],
  );

  const planText = `${context?.plan_name ?? "当前套餐"} · ${formatSubscription(
    context?.subscription_status ?? fallbackSubscriptionStatus,
  )}`;
  const rateText = `R1 ≈ ¥${formatRate(context?.zar_cny_rate ?? 0.42)}`;

  return (
    <div style={wrapStyle} aria-label="运营状态">
      <StatusPill label={southAfricaTime} detail={`${southAfricaDate} 南非时间`} />
      <StatusPill label={rateText} detail="ZAR/CNY 参考汇率" />
      <StatusPill label={planText} detail="套餐状态" />
    </div>
  );
}

function StatusPill({ label, detail }: { label: string; detail: string }) {
  return (
    <div style={pillStyle}>
      <span style={dotStyle} />
      <span style={textWrapStyle}>
        <strong style={labelStyle}>{label}</strong>
        <span style={detailStyle}>{detail}</span>
      </span>
    </div>
  );
}

function formatRate(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "--";
  return value.toFixed(2);
}

function formatSubscription(status: string) {
  if (status === "unactivated") return "未激活";
  if (status === "active") return "订阅正常";
  if (status === "trialing") return "试用中";
  if (status === "past_due") return "待续费";
  if (status === "paused") return "已暂停";
  if (status === "cancelled") return "已取消";
  return "状态未知";
}

const wrapStyle: CSSProperties = {
  minWidth: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  flexWrap: "wrap",
};

const pillStyle: CSSProperties = {
  minHeight: 30,
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  padding: "4px 9px",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  background: "#FAFAFA",
  color: "#000000",
};

const dotStyle: CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: 999,
  background: "#000000",
  flexShrink: 0,
};

const textWrapStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 1,
};

const labelStyle: CSSProperties = {
  maxWidth: 142,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  fontSize: 11,
  lineHeight: 1.1,
  fontWeight: 760,
  color: "#000000",
};

const detailStyle: CSSProperties = {
  fontSize: 9,
  lineHeight: 1.1,
  color: "#595959",
};
