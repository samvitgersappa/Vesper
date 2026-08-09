"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type AnyDict = Record<string, any>;

const PERIODS = [
  { id: "day", label: "Daily", color: "#ff7a8a" },
  { id: "week", label: "Weekly", color: "#ff9d6b" },
  { id: "month", label: "Monthly", color: "#f6c445" },
  { id: "year", label: "Yearly", color: "#4fd8e0" },
] as const;
type Period = (typeof PERIODS)[number]["id"];

const CATEGORY_COLORS = [
  "#3ddc97",
  "#4fd8e0",
  "#5b8cff",
  "#ff6d9c",
  "#f6c445",
  "#9d7bff",
];

export default function Spending() {
  const [period, setPeriod] = useState<Period>("week");
  const [summary, setSummary] = useState<AnyDict | null>(null);
  const [analysis, setAnalysis] = useState<AnyDict | null>(null);
  const [transactions, setTransactions] = useState<AnyDict[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setSummary(await api(`/spending/summary`, { period }));
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, [period]);

  useEffect(() => {
    (async () => {
      try {
        const [a, t] = await Promise.all([
          api<AnyDict>("/spending/analysis"),
          api<AnyDict>("/spending/transactions", { limit: 20 }),
        ]);
        setAnalysis(a);
        setTransactions(t.transactions ?? []);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  const buckets = summary?.buckets ?? [];
  const maxBucket = Math.max(1, ...buckets.map((b: AnyDict) => b.total));
  const current = summary?.current ?? null;
  const change = summary?.change_pct;
  const periodMeta = PERIODS.find((p) => p.id === period) ?? PERIODS[1];

  return (
    <>
      <PageHeader
        title="Spending"
        subtitle="Every rupee, sorted. Track spend across the day, week, month and year and spot the habits quietly eating your budget."
        accent="var(--spend)"
        accentB="#ff9d6b"
      />
      {error && <div className="error">{error}</div>}
      <section className="spending-banner"><div><span className="eyebrow">Money, with less noise</span><h2>{current?.total ? `₹${Number(current.total).toLocaleString("en-IN")} in focus` : "A quiet spending window"}</h2><p>Use the period switcher to see the rhythm, not just the total.</p></div><div className="spending-mark">₹</div></section>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {PERIODS.map((p) => (
          <button
            key={p.id}
            className="pill"
            style={
              period === p.id
                ? {
                    background: `linear-gradient(120deg, ${p.color}, ${PERIODS[PERIODS.indexOf(p) + 1]?.color ?? p.color})`,
                    color: "#fff",
                    border: "none",
                    boxShadow: `0 6px 20px ${p.color}55`,
                  }
                : { borderColor: "var(--border)" }
            }
            onClick={() => setPeriod(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid">
        <div className="card">
          <h2>This {periodMeta.label}</h2>
          <div className="big grad" style={{ "--big-a": "#ff6d9c", "--big-b": "#ff9d6b" } as React.CSSProperties}>
            {current?.total ? `₹${Number(current.total).toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="muted">
            {current?.count ?? 0} expenses
            {change != null && (
              <span className={change >= 0 ? "bad" : "good"}>
                {" "}
                · {change >= 0 ? "+" : ""}
                {change}% vs previous
              </span>
            )}
          </div>
        </div>
        <div className="card">
          <h2>Window Total</h2>
          <div className="big grad" style={{ "--big-a": "#f6c445", "--big-b": "#f0a84b" } as React.CSSProperties}>
            {summary?.total ? `₹${Number(summary.total).toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="muted">
            avg ₹{Number(summary?.avg_per_bucket ?? 0).toLocaleString("en-IN")} /{" "}
            {periodMeta.label.toLowerCase()}
          </div>
        </div>
        <div className="card">
          <h2>Lifetime</h2>
          <div className="big grad" style={{ "--big-a": "#4fd8e0", "--big-b": "#3ddc97" } as React.CSSProperties}>
            {analysis?.total ? `₹${Number(analysis.total).toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="muted">
            {analysis?.count ?? 0} expenses · avg ₹
            {Number(analysis?.avg_transaction ?? 0).toLocaleString("en-IN")}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Spend Trend</h2>
        {buckets.length ? (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 180 }}>
            {buckets.map((b: AnyDict, i: number) => (
              <div
                key={i}
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 4,
                  minWidth: 0,
                }}
                title={`${b.label}: ₹${Number(b.total).toLocaleString("en-IN")}`}
              >
                <div
                  style={{
                    width: "100%",
                    maxWidth: 40,
                    height: Math.max(2, (b.total / maxBucket) * 140),
                    background:
                      i === buckets.length - 1
                        ? periodMeta.color
                        : "color-mix(in srgb, var(--spend) 35%, #3a4150)",
                    borderRadius: 4,
                    boxShadow: i === buckets.length - 1 ? `0 0 18px ${periodMeta.color}66` : "none",
                  }}
                />
                <div
                  className="muted"
                  style={{
                    fontSize: 10,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: "100%",
                  }}
                >
                  {b.label.slice(5)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="data-empty"><div><strong>No spending here</strong><span>This window is clear.</span></div></div>
        )}
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>By Category</h2>
          {analysis?.categories?.length ? (
            <ul className="list">
              {analysis.categories.map((c: AnyDict, ci: number) => {
                const color = CATEGORY_COLORS[ci % CATEGORY_COLORS.length];
                return (
                  <li key={c.category} style={{ display: "block" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>
                        <span className="nav-dot" style={{ background: color, color }} />
                        {c.category}
                      </span>
                      <span className="muted">
                        ₹{Number(c.total).toLocaleString("en-IN")} · {c.share_pct}%
                      </span>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${c.share_pct}%`,
                          background: `linear-gradient(90deg, ${color}, ${CATEGORY_COLORS[(ci + 1) % CATEGORY_COLORS.length]})`,
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="data-empty"><div><strong>No categories yet</strong><span>Logged expenses will find their shape here.</span></div></div>
          )}
        </div>

        <div className="card">
          <h2>Habits &amp; Trends</h2>
          <ul className="list">
            {(analysis?.habits ?? ["No spending logged yet."]).map(
              (h: string, i: number) => (
                <li key={i}>
                  <span className="nav-dot" style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length], color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
                  {h}
                </li>
              ),
            )}
          </ul>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Recent Expenses</h2>
        {transactions.length ? (
          <ul className="list">
            {transactions.map((t: AnyDict) => (
              <li key={t.id}>
                <span>{t.category}</span>
                <span className="muted">
                  {t.date} · ₹{Number(t.amount).toLocaleString("en-IN")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="data-empty"><div><strong>No expenses logged</strong><span>Nothing to reconcile yet.</span></div></div>
        )}
      </div>
    </>
  );
}
