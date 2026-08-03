"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type Strategy = {
  trader_id: string;
  name: string;
  short: string;
  type: string;
  description: string;
  total_equity?: number;
  day_pnl_pct?: number;
  n_positions?: number;
};

type AnyDict = Record<string, any>;

const TABS = [
  { id: "portfolio", label: "Portfolio" },
  { id: "trades", label: "Trades" },
  { id: "signals", label: "Signals" },
  { id: "nav", label: "Performance" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const STRATEGY_COLORS = [
  "#3ddc97",
  "#4fd8e0",
  "#5b8cff",
  "#9d7bff",
  "#ff7a8a",
];

export default function Finance() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [tab, setTab] = useState<TabId>("portfolio");
  const [data, setData] = useState<AnyDict | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<AnyDict | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api<{ strategies: Strategy[] }>("/finance/strategies");
        setStrategies(res.strategies ?? []);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setError("");
      try {
        setData(null);
        const res = await api<AnyDict>(`/finance/${tab}`, { strategy: selected, limit: 60 });
        if (!cancelled) setData(res);
      } catch (e: any) {
        if (!cancelled) setError(e.message);
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [tab, selected]);

  const runEod = async () => {
    setRunning(true);
    setError("");
    try {
      const base = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8123").replace(/\/$/, "");
      const res = await fetch(`${base}/api/finance/run-eod`, {
        method: "POST",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`);
      setLastRun(await res.json());
      const fresh = await api<AnyDict>(`/finance/${tab}`, { strategy: selected, limit: 60 });
      setData(fresh);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  const activeStrategy =
    strategies.find((s) => s.trader_id === selected) ?? null;

  const holdings =
    selected === ""
      ? (data?.traders ?? []).flatMap((t: AnyDict) =>
          (t.holdings ?? []).map((h: AnyDict) => ({
            ...h,
            trader: t.trader_id,
          })),
        )
      : data?.traders?.[0]?.holdings ?? data?.holdings ?? [];

  const rows =
    tab === "portfolio"
      ? holdings
      : tab === "nav"
        ? Object.entries(data?.nav ?? {}).flatMap(([trader, series]: any) =>
            (series ?? []).map((r: AnyDict) => ({ ...r, trader })),
          )
        : data?.trades ?? data?.signals ?? [];

  const portfolioValue =
    tab === "portfolio"
      ? selected === ""
        ? (data?.traders ?? []).reduce(
            (sum: number, t: AnyDict) =>
              sum +
              (t.cash?.available ?? 0) +
              (Array.isArray(t.holdings)
                ? t.holdings.reduce(
                    (h: number, x: AnyDict) => h + (x.market_value ?? 0),
                    0,
                  )
                : 0),
            0,
          )
        : data?.traders?.[0]?.total_equity ?? null
      : null;

  return (
    <>
      <PageHeader
        title="Wealth"
        subtitle="Five paper strategies run a daily EOD routine against live factor data — review holdings, trades and performance per strategy."
        accent="var(--finance)"
        accentB="#4fd8e0"
        actions={
          <button className="pill active" onClick={runEod} disabled={running}>
            {running ? "Running EOD…" : "▶ Run EOD"}
          </button>
        }
      />
      {error && <div className="error">{error}</div>}

      {lastRun && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>EOD Run · {lastRun.date}</h2>
          <div className="stat-grid">
            {(lastRun.traders ?? []).map((t: AnyDict) => (
              <div key={t.trader_id}>
                <div className="stat-label">{t.trader_id}</div>
                <div>
                  {t.trades ?? 0} trades · ₹
                  {Number(t.total_equity ?? 0).toLocaleString("en-IN")}
                </div>
              </div>
            ))}
          </div>
          <div className="muted" style={{ marginTop: 8 }}>
            {lastRun.trades ?? 0} total trades executed
            {lastRun.degraded ? " (degraded — no prices)" : ""}
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        {strategies.map((s, i) => {
          const active = selected === s.trader_id;
          const c = STRATEGY_COLORS[i % STRATEGY_COLORS.length];
          return (
            <button
              key={s.trader_id}
              className="pill"
              style={
                active
                  ? {
                      background: `linear-gradient(120deg, ${c}, ${STRATEGY_COLORS[(i + 1) % STRATEGY_COLORS.length]})`,
                      color: "#fff",
                      border: "none",
                      boxShadow: `0 6px 20px ${c}55`,
                    }
                  : { borderColor: "var(--border)" }
              }
              onClick={() => setSelected(active ? "" : s.trader_id)}
            >
              {s.short}
            </button>
          );
        })}
        {selected !== "" && (
          <button className="pill" onClick={() => setSelected("")}>
            ✕ Clear
          </button>
        )}
      </div>

      {selected !== "" && activeStrategy && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="big grad" style={{ "--big-a": "#3ddc97", "--big-b": "#4fd8e0" } as React.CSSProperties}>
            {activeStrategy.name}
          </div>
          <div className="muted" style={{ marginTop: 4 }}>
            {activeStrategy.description}
            {activeStrategy.day_pnl_pct != null && (
              <span className={activeStrategy.day_pnl_pct >= 0 ? "good" : "bad"}>
                {" "}
                · Day {activeStrategy.day_pnl_pct >= 0 ? "+" : ""}
                {activeStrategy.day_pnl_pct}%
              </span>
            )}
            {activeStrategy.n_positions != null && (
              <span> · {activeStrategy.n_positions} positions</span>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`pill${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "portfolio" && data && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Total Portfolio Value</h2>
          <div className="big grad" style={{ "--big-a": "#3ddc97", "--big-b": "#4fd8e0" } as React.CSSProperties}>
            {portfolioValue ? `₹${Number(portfolioValue).toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="muted" style={{ marginTop: 4 }}>
            {selected === ""
              ? `${data.traders?.length ?? 0} strategies · paper`
              : `${activeStrategy?.short ?? selected} · paper`}
          </div>
        </div>
      )}

      {tab === "nav" && data?.nav && Object.keys(data.nav).length > 0 && (
        <NavChart nav={data.nav} />
      )}

      {rows.length ? (
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                {Object.keys(rows[0] ?? {}).slice(0, 8).map((k) => (
                  <th key={k}>{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any, i: number) => (
                <tr key={i}>
                  {Object.values(r).slice(0, 8).map((v: any, j: number) => (
                    <td key={j}>
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="muted">No data.</div>
      )}
    </>
  );
}

function strategyBtnStyle(active: boolean) {
  return {
    cursor: "pointer",
    padding: "6px 14px",
    background: active ? "var(--accent)" : "var(--panel)",
    color: active ? "#0f1115" : "var(--text)",
    border: "1px solid var(--border)",
  } as const;
}

const NAV_COLORS = ["#3ddc97", "#4fd8e0", "#5b8cff", "#9d7bff", "#ff7a8a", "#f6c445"];

function NavChart({ nav }: { nav: AnyDict }) {
  const series = Object.entries(nav)
    .map(([trader, rows]) => ({
      trader,
      rows: (rows as AnyDict[])
        .slice()
        .reverse()
        .map((r) => ({ d: String(r.date).slice(5), v: Number(r.total_equity) })),
    }))
    .filter((s) => s.rows.length >= 2);

  const W = 1100;
  const H = 240;
  const P = { l: 60, r: 16, t: 16, b: 28 };
  const allV = series.flatMap((s) => s.rows.map((r) => r.v));
  const min = Math.min(...allV);
  const max = Math.max(...allV);
  const span = max - min || 1;
  const maxLen = Math.max(...series.map((s) => s.rows.length));

  const x = (i: number) => P.l + (i / Math.max(1, maxLen - 1)) * (W - P.l - P.r);
  const y = (v: number) => P.t + (1 - (v - min) / span) * (H - P.t - P.b);

  const ticks = Array.from({ length: 5 }, (_, i) => min + (span * i) / 4);

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2>NAV Performance</h2>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ overflow: "visible" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="3 3" />
            <text x={P.l - 8} y={y(t) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
              ₹{Math.round(t).toLocaleString("en-IN")}
            </text>
          </g>
        ))}
        {series.map((s, si) => {
          const color = NAV_COLORS[si % NAV_COLORS.length];
          const pts = s.rows
            .map((r, i) => `${x(i).toFixed(1)},${y(r.v).toFixed(1)}`)
            .join(" ");
          return (
            <g key={s.trader}>
              <polyline
                points={pts}
                fill="none"
                stroke={color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              <text x={x(s.rows.length - 1) + 6} y={y(s.rows[s.rows.length - 1].v) - 6} fontSize="10" fill={color}>
                {s.trader}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
