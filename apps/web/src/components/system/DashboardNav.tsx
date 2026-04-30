"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { PackagePlus } from "lucide-react";
import type { CSSProperties } from "react";

export type DashboardNavItem = {
  href: string;
  label: string;
  note: string;
  icon?: string;
};

export function DashboardNav({
  primaryItems,
  adminItems,
}: {
  primaryItems: DashboardNavItem[];
  adminItems: DashboardNavItem[];
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (
    <div style={railStyle}>
      <NavSection title="工作流" items={primaryItems} pathname={pathname} searchParams={searchParams} />
      {adminItems.length > 0 ? (
        <NavSection title="管理员" items={adminItems} pathname={pathname} searchParams={searchParams} />
      ) : null}
    </div>
  );
}

function NavSection({
  title,
  items,
  pathname,
  searchParams,
}: {
  title: string;
  items: DashboardNavItem[];
  pathname: string;
  searchParams: ReturnType<typeof useSearchParams>;
}) {
  const activeHref = findActiveHref(items, pathname, searchParams);

  return (
    <section style={{ display: "grid", gap: 6 }}>
      <div style={sectionTitleStyle}>{title}</div>
      <div style={{ display: "grid", gap: 2 }}>
        {items.map((item) => {
          const isActive = item.href === activeHref;
          return (
            <Link key={item.href} href={item.href} style={itemStyle(isActive)}>
              <NavIcon icon={item.icon} isActive={isActive} />
              <span style={itemLabelStyle(isActive)}>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function findActiveHref(
  items: DashboardNavItem[],
  pathname: string,
  searchParams: ReturnType<typeof useSearchParams>,
) {
  return items
    .filter((item) => matchesNavItem(item.href, pathname, searchParams))
    .sort((left, right) => right.href.length - left.href.length)[0]?.href;
}

function matchesNavItem(
  href: string,
  pathname: string,
  searchParams: ReturnType<typeof useSearchParams>,
) {
  const [targetPath, queryString] = href.split("?");
  const samePath = pathname === targetPath || pathname.startsWith(`${targetPath}/`);

  if (!samePath) {
    return false;
  }

  if (!queryString) {
    return true;
  }

  const targetParams = new URLSearchParams(queryString);
  return Array.from(targetParams.entries()).every(([key, value]) => searchParams.get(key) === value);
}

function NavIcon({ icon, isActive }: { icon?: string; isActive: boolean }) {
  if (icon === "PackagePlus") {
    return (
      <span style={iconStyle(isActive)}>
        <PackagePlus size={14} strokeWidth={1.8} />
      </span>
    );
  }

  return <span style={iconStyle(isActive)}>{icon ?? "•"}</span>;
}

const railStyle: CSSProperties = {
  display: "grid",
  gap: 16,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 10,
  color: "#595959",
  fontWeight: 600,
  padding: "8px 8px 4px",
};

function itemStyle(isActive: boolean): CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 8,
    minHeight: 32,
    padding: "6px 8px",
    borderRadius: 6,
    textDecoration: "none",
    background: isActive ? "#FFFFFF" : "transparent",
    border: isActive ? "1px solid #EBEBEB" : "1px solid transparent",
    transition: "background 140ms ease, border-color 140ms ease, color 140ms ease",
  };
}

function iconStyle(isActive: boolean): CSSProperties {
  return {
    width: 18,
    height: 18,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    color: isActive ? "#000000" : "#595959",
    fontSize: 13,
    lineHeight: 1,
  };
}

function itemLabelStyle(isActive: boolean): CSSProperties {
  return {
    fontSize: 13,
    fontWeight: isActive ? 650 : 500,
    color: isActive ? "#000000" : "#595959",
  };
}
