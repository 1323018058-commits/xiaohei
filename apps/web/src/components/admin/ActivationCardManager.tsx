"use client";

import { useEffect, useState, type CSSProperties, type FormEvent } from "react";

import { ApiError, apiFetch } from "@/lib/api";

type ActivationCard = {
  card_id: string;
  code?: string | null;
  code_suffix: string;
  days: number;
  status: string;
  note?: string | null;
  redeemed_tenant_id?: string | null;
  redeemed_at?: string | null;
  voided_at?: string | null;
  created_at: string;
};

type CardListResponse = {
  cards: ActivationCard[];
};

type CardCreateResponse = {
  success: boolean;
  cards: ActivationCard[];
};

export function ActivationCardManager() {
  const [cards, setCards] = useState<ActivationCard[]>([]);
  const [newCards, setNewCards] = useState<ActivationCard[]>([]);
  const [days, setDays] = useState("7");
  const [quantity, setQuantity] = useState("1");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);

  useEffect(() => {
    void loadCards();
  }, []);

  async function loadCards() {
    setIsLoading(true);
    try {
      const data = await apiFetch<CardListResponse>("/admin/api/activation-cards");
      setCards(data.cards);
    } catch {
      setErrorMessage("天卡列表读取失败。");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsMutating(true);
    setErrorMessage("");
    setMessage("");
    setNewCards([]);
    try {
      const data = await apiFetch<CardCreateResponse>("/admin/api/activation-cards", {
        method: "POST",
        body: JSON.stringify({
          days: Number.parseInt(days, 10),
          quantity: Number.parseInt(quantity, 10),
          note: note.trim() || null,
        }),
      });
      setNewCards(data.cards);
      setMessage("已生成天卡，明文只在这里显示一次。");
      setNote("");
      await loadCards();
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.detail : "生成失败。");
    } finally {
      setIsMutating(false);
    }
  }

  async function handleVoid(card: ActivationCard) {
    const reason = window.prompt(`确认作废 ****${card.code_suffix}？请输入原因`, "manual void");
    if (!reason) return;
    setIsMutating(true);
    setErrorMessage("");
    try {
      await apiFetch(`/admin/api/activation-cards/${card.card_id}/void`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      setMessage("已作废天卡。");
      await loadCards();
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.detail : "作废失败。");
    } finally {
      setIsMutating(false);
    }
  }

  async function copyCode(code: string | null | undefined) {
    if (!code) return;
    await navigator.clipboard.writeText(code);
    setMessage("已复制天卡。");
  }

  return (
    <section style={panelStyle}>
      <div style={headerStyle}>
        <div>
          <div style={eyebrowStyle}>商业化</div>
          <div style={titleStyle}>天卡管理</div>
        </div>
        <button type="button" style={ghostButtonStyle} onClick={() => void loadCards()} disabled={isLoading}>
          刷新
        </button>
      </div>

      <form onSubmit={handleCreate} style={formStyle}>
        <input value={days} onChange={(event) => setDays(event.target.value)} style={inputStyle} placeholder="天数" />
        <input value={quantity} onChange={(event) => setQuantity(event.target.value)} style={inputStyle} placeholder="数量" />
        <input value={note} onChange={(event) => setNote(event.target.value)} style={inputStyle} placeholder="备注，可选" />
        <button type="submit" style={primaryButtonStyle} disabled={isMutating}>
          生成
        </button>
      </form>

      {newCards.length > 0 ? (
        <div style={newCardBoxStyle}>
          {newCards.map((card) => (
            <button key={card.card_id} type="button" style={codeButtonStyle} onClick={() => void copyCode(card.code)}>
              {card.code}
            </button>
          ))}
        </div>
      ) : null}

      {message ? <div style={successStyle}>{message}</div> : null}
      {errorMessage ? <div style={errorStyle}>{errorMessage}</div> : null}

      <div style={listStyle}>
        {cards.slice(0, 8).map((card) => (
          <div key={card.card_id} style={rowStyle}>
            <div>
              <strong>****{card.code_suffix}</strong>
              <span style={metaStyle}>{card.days} 天 · {formatStatus(card.status)}</span>
              <span style={metaStyle}>{card.note || formatDate(card.created_at)}</span>
            </div>
            {card.status === "active" ? (
              <button type="button" style={ghostButtonStyle} disabled={isMutating} onClick={() => void handleVoid(card)}>
                作废
              </button>
            ) : null}
          </div>
        ))}
        {cards.length === 0 ? <div style={emptyStyle}>{isLoading ? "读取中..." : "暂无天卡"}</div> : null}
      </div>
    </section>
  );
}

function formatStatus(status: string) {
  if (status === "active") return "未使用";
  if (status === "redeemed") return "已兑换";
  if (status === "voided") return "已作废";
  return status;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString();
}

const panelStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  background: "#FFFFFF",
  padding: 14,
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
};

const eyebrowStyle: CSSProperties = {
  fontSize: 10,
  color: "#595959",
  fontWeight: 800,
};

const titleStyle: CSSProperties = {
  marginTop: 2,
  fontSize: 15,
  color: "#000000",
  fontWeight: 900,
};

const formStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "64px 64px minmax(0, 1fr) 64px",
  gap: 8,
};

const inputStyle: CSSProperties = {
  minWidth: 0,
  height: 34,
  border: "1px solid #EBEBEB",
  borderRadius: 4,
  padding: "0 9px",
  fontSize: 12,
  outline: "none",
};

const primaryButtonStyle: CSSProperties = {
  height: 34,
  border: "1px solid #000000",
  borderRadius: 4,
  background: "#000000",
  color: "#FFFFFF",
  fontSize: 12,
  fontWeight: 850,
  cursor: "pointer",
};

const ghostButtonStyle: CSSProperties = {
  height: 30,
  border: "1px solid #000000",
  borderRadius: 4,
  background: "#FFFFFF",
  color: "#000000",
  padding: "0 9px",
  fontSize: 12,
  fontWeight: 750,
  cursor: "pointer",
};

const newCardBoxStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  border: "1px solid #000000",
  borderRadius: 4,
  padding: 8,
  background: "#FAFAFA",
};

const codeButtonStyle: CSSProperties = {
  border: "1px dashed #000000",
  borderRadius: 4,
  background: "#FFFFFF",
  padding: "7px 8px",
  textAlign: "left",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 12,
  cursor: "copy",
};

const listStyle: CSSProperties = {
  display: "grid",
  gap: 7,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  borderTop: "1px solid #F0F0F0",
  paddingTop: 8,
};

const metaStyle: CSSProperties = {
  display: "block",
  marginTop: 2,
  color: "#595959",
  fontSize: 11,
};

const successStyle: CSSProperties = {
  border: "1px solid #15803D",
  borderRadius: 4,
  padding: "7px 8px",
  background: "#F0FDF4",
  color: "#166534",
  fontSize: 12,
};

const errorStyle: CSSProperties = {
  border: "1px solid #DC2626",
  borderRadius: 4,
  padding: "7px 8px",
  background: "#FEF2F2",
  color: "#B91C1C",
  fontSize: 12,
};

const emptyStyle: CSSProperties = {
  color: "#595959",
  fontSize: 12,
};
