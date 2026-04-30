import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { CSSProperties, ReactNode } from "react";

import { DashboardNav, type DashboardNavItem } from "@/components/system/DashboardNav";
import { DashboardStatusBadges } from "@/components/system/DashboardStatusBadges";
import { CurrentUserBadge } from "@/components/system/CurrentUserBadge";
import { LogoutButton } from "@/components/system/LogoutButton";
import { ActivationPanel } from "@/components/subscription/ActivationPanel";
import { getServerSessionInfo } from "@/lib/server-session";

const primaryItems: DashboardNavItem[] = [
  { href: "/dashboard", label: "首页看板", note: "看今天的结果、风险和下一步动作", icon: "▦" },
  { href: "/stores", label: "店铺管理", note: "绑定店铺、校验凭证、执行同步", icon: "●" },
  { href: "/selection", label: "选品库", note: "Takealot 全站商品情报筛选", icon: "◇" },
  { href: "/products", label: "商品管理", note: "维护高密商品列表与自定义字段", icon: "◫" },
  { href: "/bidding", label: "自动竞价", note: "按 SKU 管理保护底价和策略", icon: "↗" },
  { href: "/listing", label: "上架记录", note: "只看最终结果：已上架或失败", icon: "▤" },
  { href: "/orders", label: "订单中心", note: "同步订单并查看关键履约信息", icon: "◆" },
];

const adminItems: DashboardNavItem[] = [
  { href: "/webhooks", label: "平台事件", note: "查看平台事件写入结果和异常", icon: "◎" },
  { href: "/tasks", label: "任务中心", note: "查看异步任务、重试和排障", icon: "◷" },
  { href: "/admin", label: "平台管理", note: "处理用户、租户、订阅与审计", icon: "⚙" },
];

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  if (!cookieStore.get("erp_session")) {
    redirect("/login");
  }

  const session = await getServerSessionInfo();
  if (!session) {
    redirect("/login");
  }

  const role = session.user.role;
  const canSeeAdminModules = ["super_admin", "tenant_admin"].includes(role);

  if (session.subscription_status === "unactivated") {
    return (
      <ActivationPanel
        username={session.user.username}
        subscriptionStatus={session.subscription_status}
      />
    );
  }

  return (
    <div style={shellStyle}>
      <aside style={sidebarStyle}>
        <div style={{ display: "grid", alignContent: "space-between", minHeight: "100%" }}>
          <div style={{ display: "grid", gap: 12 }}>
            <div style={brandCardStyle}>
              <div style={brandMarkStyle}>小黑</div>
              <div>
                <div style={brandTitleStyle}>小黑ERP</div>
                <div style={brandCopyStyle}>Takealot 运营台</div>
              </div>
            </div>

            <DashboardNav
              primaryItems={primaryItems}
              adminItems={canSeeAdminModules ? adminItems : []}
            />
          </div>

          <div style={sideFooterStyle}>帮助文档</div>
        </div>
      </aside>

      <div style={mainColumnStyle}>
        <header style={topbarStyle}>
          <DashboardStatusBadges fallbackSubscriptionStatus={session.subscription_status} />
          <div style={topbarActionsStyle}>
            <a
                    href="/downloads/xiaohei-takealot-extension-latest.zip"
              download
              title="下载小黑 Takealot Chrome 插件，解压后加载 manifest.json 所在文件夹"
              style={extensionDownloadStyle}
            >
              下载插件
            </a>
            <CurrentUserBadge
              username={session.user.username}
              role={session.user.role}
              subscriptionStatus={session.subscription_status}
            />
            <LogoutButton />
          </div>
        </header>

        <main style={contentWrapStyle}>{children}</main>
      </div>
    </div>
  );
}

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  gridTemplateColumns: "156px minmax(0, 1fr)",
  background: "#FAFAFA",
};

const sidebarStyle: CSSProperties = {
  padding: "12px 10px",
  background: "#FAFAFA",
  borderRight: "1px solid #EBEBEB",
  position: "sticky",
  top: 0,
  height: "100vh",
};

const brandCardStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 6px 8px",
};

const brandTitleStyle: CSSProperties = {
  fontSize: 14,
  lineHeight: 1.1,
  color: "#111111",
  fontWeight: 900,
};

const brandCopyStyle: CSSProperties = {
  marginTop: 2,
  fontSize: 10,
  color: "#595959",
};

const brandMarkStyle: CSSProperties = {
  width: 34,
  height: 24,
  borderRadius: 6,
  display: "grid",
  placeItems: "center",
  background: "#000000",
  color: "#ffffff",
  fontSize: 12,
  fontWeight: 900,
};

const sideFooterStyle: CSSProperties = {
  margin: "10px 6px 0",
  padding: "8px 9px",
  borderRadius: 6,
  color: "#595959",
  fontSize: 12,
  fontWeight: 620,
};

const mainColumnStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gridTemplateRows: "auto minmax(0, 1fr)",
  padding: 0,
};

const topbarStyle: CSSProperties = {
  minHeight: 46,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  padding: "7px 24px",
  background: "#FFFFFF",
  borderBottom: "1px solid #EBEBEB",
  position: "sticky",
  top: 0,
  zIndex: 10,
};

const topbarActionsStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 10,
  minWidth: 0,
};

const extensionDownloadStyle: CSSProperties = {
  minHeight: 28,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "4px 10px",
  border: "1px solid #111111",
  borderRadius: 4,
  background: "#FFF7CC",
  color: "#111111",
  boxShadow: "3px 3px 0 #111111",
  fontSize: 12,
  fontWeight: 900,
  lineHeight: 1,
  textDecoration: "none",
  whiteSpace: "nowrap",
};

const contentWrapStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  alignContent: "start",
  padding: "24px",
};
