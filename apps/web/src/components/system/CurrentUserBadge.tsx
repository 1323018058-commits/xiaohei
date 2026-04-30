import type { CSSProperties } from "react";

export function CurrentUserBadge({
  username,
  role,
  subscriptionStatus,
}: {
  username: string;
  role: string;
  subscriptionStatus: string;
}) {
  return (
    <div style={wrapStyle}>
      <div style={avatarStyle}>{username.slice(0, 1).toUpperCase()}</div>
      <div style={{ display: "grid", gap: 2 }}>
        <strong style={nameStyle}>{username}</strong>
        <span style={metaStyle}>
          {formatRole(role)} · {formatSubscription(subscriptionStatus)}
        </span>
      </div>
    </div>
  );
}

function formatRole(role: string) {
  if (role === "super_admin") return "平台管理员";
  if (role === "tenant_admin") return "租户管理员";
  return "成员账号";
}

function formatSubscription(status: string) {
  if (status === "active") return "订阅正常";
  if (status === "trialing") return "试用中";
  if (status === "past_due") return "待续费";
  if (status === "paused") return "已暂停";
  return "状态未知";
}

const wrapStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  minWidth: 0,
};

const avatarStyle: CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 6,
  display: "grid",
  placeItems: "center",
  background: "#FAFAFA",
  border: "1px solid #EBEBEB",
  color: "#000000",
  fontSize: 12,
  fontWeight: 760,
  flexShrink: 0,
};

const nameStyle: CSSProperties = {
  fontSize: 12,
  letterSpacing: "-0.01em",
  color: "#000000",
};

const metaStyle: CSSProperties = {
  fontSize: 11,
  lineHeight: 1.4,
  color: "#595959",
};
