"use client";

import { useRouter } from "next/navigation";
import { useState, type CSSProperties } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleLogout() {
    setIsSubmitting(true);

    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      router.push("/login");
      router.refresh();
      setIsSubmitting(false);
    }
  }

  return (
    <button type="button" onClick={handleLogout} disabled={isSubmitting} style={buttonStyle(isSubmitting)}>
      {isSubmitting ? "退出中…" : "退出登录"}
    </button>
  );
}

function buttonStyle(isSubmitting: boolean): CSSProperties {
  return {
    border: "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "7px 10px",
    background: "#ffffff",
    color: "#000000",
    fontSize: 12,
    fontWeight: 650,
    cursor: isSubmitting ? "not-allowed" : "pointer",
    boxShadow: "none",
    opacity: isSubmitting ? 0.68 : 1,
  };
}
