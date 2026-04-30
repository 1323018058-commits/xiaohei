import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "Xiaohei ERP",
  description: "Takealot 商业化卖家工作台",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          background: "#f6f6f4",
          color: "#141414",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif',
        }}
      >
        {children}
      </body>
    </html>
  );
}
