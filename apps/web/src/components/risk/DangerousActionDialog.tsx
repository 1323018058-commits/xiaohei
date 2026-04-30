"use client";

type DangerousActionDialogProps = {
  title: string;
  open: boolean;
  riskText: string;
  confirmLabel: string;
  reason: string;
  isSubmitting?: boolean;
  onReasonChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

export function DangerousActionDialog({
  title,
  open,
  riskText,
  confirmLabel,
  reason,
  isSubmitting = false,
  onReasonChange,
  onConfirm,
  onCancel,
}: DangerousActionDialogProps) {
  if (!open) return null;

  return (
    <div style={backdropStyle}>
      <div style={dialogStyle}>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={titleStyle}>{title}</div>
          <div style={riskTextStyle}>{riskText}</div>
        </div>

        <textarea
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
          placeholder="请输入操作原因"
          rows={4}
          style={textareaStyle}
        />

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" onClick={onCancel} style={secondaryButtonStyle}>
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting || !reason.trim()}
            style={primaryButtonStyle}
          >
            {isSubmitting ? "处理中..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

const backdropStyle = {
  position: "fixed",
  inset: 0,
  background: "rgba(0, 0, 0, 0.32)",
  display: "grid",
  placeItems: "center",
  padding: 24,
  zIndex: 50,
} satisfies React.CSSProperties;

const dialogStyle = {
  width: "min(560px, 100%)",
  background: "#ffffff",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 20,
  boxShadow: "none",
  display: "grid",
  gap: 16,
} satisfies React.CSSProperties;

const titleStyle = {
  fontSize: 20,
  fontWeight: 700,
} satisfies React.CSSProperties;

const riskTextStyle = {
  color: "#D9363E",
  background: "#FFFFFF",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "12px 14px",
  fontSize: 14,
  lineHeight: 1.5,
} satisfies React.CSSProperties;

const textareaStyle = {
  width: "100%",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "12px 14px",
  fontSize: 14,
  resize: "vertical" as const,
} satisfies React.CSSProperties;

const secondaryButtonStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "10px 14px",
  background: "#ffffff",
  cursor: "pointer",
  fontWeight: 600,
} satisfies React.CSSProperties;

const primaryButtonStyle = {
  border: "1px solid #000000",
  borderRadius: 6,
  padding: "10px 14px",
  background: "#000000",
  color: "#ffffff",
  cursor: "pointer",
  fontWeight: 600,
} satisfies React.CSSProperties;
