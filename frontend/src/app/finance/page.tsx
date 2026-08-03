"use client";

import { useEffect, useMemo, useState } from "react";

import { api, fmtDate } from "../../lib/api";
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

type Holding = {
  ticker: string;
  qty: number;
  avg_price?: number;
  last_price?: number;
  market_value?: number;
};

type Trader = {
  trader_id: string;
  cash?: { available?: number; settled?: number; blocked?: number };
  holdings?: Holding[];
  holdings_value?: number;
  total_equity?: number;
  day_pnl_pct?: number;
  nav_date?: string;
};

type TradeRow = {
  trader_id: string;
  date: string;
  symbol: string;
  side: string;
  qty: number;
  signal_price?: number;
  fill_price?: number;
  realized_pnl?: number;
};

type SignalRow = {
  trader_id: string;
  symbol: string;
  side: string;
  signal_price?: number;
  fill_price?: number;
  status: string;
  date: string;
};

type AnyDict = Record<string, any>;

const TABS = [
  { id: "portfolio", label: "Portfolio" },
  { id: "trades", label: "Trades" },
  { id: "signals", label: "Signals" },
  { id: "nav", label: "Performance" },
] as const;
type TabId = (typeof TABS)[number]["id"];

// One color per strategy (index-aligned); catalyst_swing is the gold 6th.
const STRATEGY_COLORS = [
  "#3ddc97",
  "#4fd8e0",
  "#5b8cff",
  "#9d7bff",
  "#ff7a8a",
  "#f6c445",
];

// ── Formatting helpers ────────────────────────────────────────────────
function inr(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function inrFull(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function pct(v?: number | null, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function price(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Pnl({ v, abs }: { v?: number | null; abs?: boolean }) {
  if (v == null || Number.isNaN(v)) return <span className="muted">—</span>;
  const cls = v > 0 ? "good" : v < 0 ? "bad" : "muted";
  const text = abs ? inrFull(v) : pct(v);
  return <span className={cls}>{v > 0 ? "+" : ""}{text}</span>;
}

function SideBadge({ side }: { side: string }) {
  const s = String(side).toUpperCase();
  return <span className={`badge ${s === "BUY" ? "buy" : "sell"}`}>{s}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const s = String(status).toLowerCase();
  const cls = ["executed", "filled", "done"].includes(s) ? "executed" : s === "triggered" ? "triggered" : "pending";
  return <span className={`badge ${cls}`}>{s}</span>;
}

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
        const res = await api<AnyDict>(`/finance/${tab}`, { strategy: selected, limit: 80 });
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
      const [fresh, freshStrats] = await Promise.all([
        api<AnyDict>(`/finance/${tab}`, { strategy: selected, limit: 80 }),
        api<{ strategies: Strategy[] }>("/finance/strategies"),
      ]);
      setData(fresh);
      setStrategies(freshStrats.strategies ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  const meta = useMemo(() => {
    const byId: Record<string, Strategy> = {};
    strategies.forEach((s, i) => {
      byId[s.trader_id] = { ...s, _color: STRATEGY_COLORS[i % STRATEGY_COLORS.length] } as any;
    });
    return byId;
  }, [strategies]);

  const colorFor = (tid: string) => (meta[tid] as any)?._color ?? "#5b8cff";

  const traders: Trader[] = data?.traders ?? [];
  const selectedMeta = selected ? meta[selected] ?? null : null;

  // Portfolio-tab aggregate.
  const summary = useMemo(() => {
    if (tab !== "portfolio" || !data) return null;
    const active = selected ? traders.filter((t) => t.trader_id === selected) : traders;
    let value = 0;
    let cash = 0;
    let invested = 0;
    let positions = 0;
    let dayRs = 0;
    for (const t of active) {
      const hv = t.holdings_value ?? t.holdings?.reduce((s, h) => s + (h.market_value ?? 0), 0) ?? 0;
      const eq = t.total_equity ?? (t.cash?.available ?? 0) + hv;
      value += eq;
      cash += t.cash?.available ?? 0;
      invested += hv;
      positions += t.holdings?.length ?? 0;
      if (t.day_pnl_pct != null && t.total_equity != null) dayRs += (t.day_pnl_pct / 100) * t.total_equity;
    }
    const dayPct = value ? (dayRs / value) * 100 : null;
    return { value, cash, invested, positions, dayRs, dayPct, nTraders: active.length };
  }, [data, tab, selected, traders]);

  const totalValue = summary?.value ?? null;
  const maxEquity = Math.max(1, ...strategies.map((s) => s.total_equity ?? 0));

  return (
    <>
      <PageHeader
        title="Wealth"
        subtitle="Six paper strategies run a daily EOD routine against live factor data — review holdings, trades and performance per strategy."
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
          <h2>EOD Run · {fmtDate(lastRun.date)}</h2>
          <div className="stat-grid">
            {(lastRun.traders ?? []).map((t: AnyDict) => (
              <div key={t.trader_id} style={{ minWidth: 150 }}>
                <div className="stat-label">{meta[t.trader_id]?.short ?? t.trader_id}</div>
                <div>
                  {t.trades ?? 0} trades · {inr(t.total_equity)}
                  {t.realized_pnl != null && (
                    <span> · PnL <Pnl v={t.realized_pnl} abs /></span>
                  )}
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

      {/* Strategy cards */}
      <div className="strat-grid">
        {strategies.map((s) => {
          const c = colorFor(s.trader_id);
          const active = selected === s.trader_id;
          const eq = s.total_equity ?? 0;
          const weight = totalValue ? (eq / totalValue) * 100 : 0;
          const dp = s.day_pnl_pct;
          return (
            <button
              key={s.trader_id}
              className={`strat-card${active ? " sel" : ""}`}
              style={{ "--sc": c } as React.CSSProperties}
              onClick={() => setSelected(active ? "" : s.trader_id)}
              title={s.description}
            >
              <div className="sc-top">
                <span className="sc-short">{s.short}</span>
                <span className={`sc-chip ${dp == null ? "neutral" : dp >= 0 ? "good" : "bad"}`}>
                  {dp == null ? "—" : pct(dp)}
                </span>
              </div>
              <div className="sc-name">{s.name}</div>
              <div className="sc-eq">{inr(eq)}</div>
              <div className="sc-foot">
                <span>{s.n_positions ?? 0} positions</span>
                <span>{totalValue ? `${weight.toFixed(1)}%` : ""}</span>
              </div>
              <div className="sc-bar">
                <i style={{ width: `${(eq / maxEquity) * 100}%` }} />
              </div>
            </button>
          );
        })}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {TABS.map((t) => (
          <button key={t.id} className={`pill${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
        {selected !== "" && (
          <button className="pill" onClick={() => setSelected("")}>
            ✕ Clear filter
          </button>
        )}
      </div>

      {tab === "portfolio" && data && (
        <>
          <div className="stat-cards">
            <div className="stat-card">
              <span className="stat-label">Total Portfolio Value</span>
              <div className="stat-num" style={{ color: "var(--finance)" }}>
                {inr(totalValue)}
              </div>
              <div className="stat-sub">
                {summary?.nTraders ?? traders.length} strategies · paper
              </div>
            </div>
            <div className="stat-card">
              <span className="stat-label">Invested</span>
              <div className="stat-num">{inr(summary?.invested)}</div>
              <div className="stat-sub">
                {summary ? ((summary.invested / summary.value) * 100).toFixed(0) : 0}% of equity deployed
              </div>
            </div>
            <div className="stat-card">
              <span className="stat-label">Available Cash</span>
              <div className="stat-num">{inr(summary?.cash)}</div>
              <div className="stat-sub">
                {summary?.positions ?? 0} open positions
              </div>
            </div>
            <div className="stat-card">
              <span className="stat-label">Day PnL</span>
              <div className="stat-num">
                <Pnl v={summary?.dayRs} abs />
              </div>
              <div className="stat-sub">
                <Pnl v={summary?.dayPct} /> today
              </div>
            </div>
          </div>

          {selectedMeta && (
            <div className="card" style={{ marginBottom: 16 }}>
              <h2>{selectedMeta.name}</h2>
              <div className="muted">{selectedMeta.description}</div>
              <div className="stat-grid">
                <div>
                  <div className="stat-label">Equity</div>
                  <div className="big">{inr(traders[0]?.total_equity)}</div>
                </div>
                <div>
                  <div className="stat-label">Day PnL</div>
                  <div className="big"><Pnl v={traders[0]?.day_pnl_pct} /></div>
                </div>
                <div>
                  <div className="stat-label">Positions</div>
                  <div className="big">{traders[0]?.holdings?.length ?? 0}</div>
                </div>
                <div>
                  <div className="stat-label">Cash</div>
                  <div className="big">{inr(traders[0]?.cash?.available)}</div>
                </div>
              </div>
            </div>
          )}

          {traders.length === 0 ? (
            <div className="muted">No portfolio data.</div>
          ) : (
            traders.map((t) => <HoldingsGroup key={t.trader_id} trader={t} name={meta[t.trader_id]?.name ?? t.trader_id} color={colorFor(t.trader_id)} />)
          )}
        </>
      )}

      {tab === "nav" && data?.nav && Object.keys(data.nav).length > 0 && <NavPanel nav={data.nav} />}

      {tab === "trades" && (
        <TradesTable rows={(data?.trades ?? []) as TradeRow[]} meta={meta} colorFor={colorFor} />
      )}

      {tab === "signals" && (
        <SignalsTable rows={(data?.signals ?? []) as SignalRow[]} meta={meta} colorFor={colorFor} />
      )}
    </>
  );
}

// ── Portfolio: one grouped card per strategy ──────────────────────────
function HoldingsGroup({ trader, name, color }: { trader: Trader; name: string; color: string }) {
  const hs = trader.holdings ?? [];
  const invested = trader.holdings_value ?? hs.reduce((s, h) => s + (h.market_value ?? 0), 0);
  const totalEquity = trader.total_equity ?? invested + (trader.cash?.available ?? 0);

  const rows = hs
    .map((h) => ({
      ...h,
      cost: (h.avg_price ?? 0) * h.qty,
      pnl: (h.market_value ?? 0) - (h.avg_price ?? 0) * h.qty,
      pnlPct: h.avg_price ? (((h.last_price ?? 0) - h.avg_price) / h.avg_price) * 100 : null,
      weight: invested ? ((h.market_value ?? 0) / invested) * 100 : 0,
    }))
    .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0));

  return (
    <div className="card group-card">
      <div className="group-head">
        <div>
          <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
            {name}
          </h3>
          <div className="gh-sub">
            {hs.length} position{hs.length === 1 ? "" : "s"} · {inr(totalEquity)} equity
          </div>
        </div>
        <div className="gh-sub" style={{ textAlign: "right" }}>
          Day <Pnl v={trader.day_pnl_pct} />
        </div>
      </div>
      <div className="card-body">
        {rows.length === 0 ? (
          <div className="muted" style={{ padding: 16 }}>No open positions.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Avg Price</th>
                <th className="num">Last Price</th>
                <th className="num">Market Value</th>
                <th className="num">Unrealized PnL</th>
                <th className="num">Return</th>
                <th className="num">Weight</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ticker}>
                  <td><span className="sym">{r.ticker.replace(/\.NS$/, "")}</span></td>
                  <td className="num">{r.qty.toLocaleString("en-IN")}</td>
                  <td className="num">{price(r.avg_price)}</td>
                  <td className="num">{price(r.last_price)}</td>
                  <td className="num">{inr(r.market_value)}</td>
                  <td className="num"><Pnl v={r.pnl} abs /></td>
                  <td className="num"><Pnl v={r.pnlPct} /></td>
                  <td className="num">{r.weight.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="tfoot">
                <td colSpan={4}>Total · {rows.length} positions</td>
                <td className="num">{inr(invested)}</td>
                <td className="num">
                  <Pnl
                    v={rows.reduce((s, r) => s + (r.pnl ?? 0), 0)}
                    abs
                  />
                </td>
                <td className="num" colSpan={2} />
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Trades ─────────────────────────────────────────────────────────────
function TradesTable({ rows, meta, colorFor }: { rows: TradeRow[]; meta: Record<string, Strategy>; colorFor: (t: string) => string }) {
  if (!rows.length) return <div className="muted">No trades yet.</div>;
  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Strategy</th>
            <th>Symbol</th>
            <th>Side</th>
            <th className="num">Qty</th>
            <th className="num">Signal</th>
            <th className="num">Fill</th>
            <th className="num">Realized PnL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="muted">{fmtDate(r.date)}</td>
              <td>
                <span style={{ color: colorFor(r.trader_id), fontWeight: 600 }}>
                  {meta[r.trader_id]?.short ?? r.trader_id}
                </span>
              </td>
              <td><span className="sym">{r.symbol.replace(/\.NS$/, "")}</span></td>
              <td><SideBadge side={r.side} /></td>
              <td className="num">{r.qty.toLocaleString("en-IN")}</td>
              <td className="num">{price(r.signal_price)}</td>
              <td className="num">{price(r.fill_price)}</td>
              <td className="num"><Pnl v={r.realized_pnl} abs /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Signals ────────────────────────────────────────────────────────────
function SignalsTable({ rows, meta, colorFor }: { rows: SignalRow[]; meta: Record<string, Strategy>; colorFor: (t: string) => string }) {
  if (!rows.length) return <div className="muted">No signals.</div>;
  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Strategy</th>
            <th>Symbol</th>
            <th>Side</th>
            <th className="num">Signal</th>
            <th className="num">Fill</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="muted">{fmtDate(r.date)}</td>
              <td>
                <span style={{ color: colorFor(r.trader_id), fontWeight: 600 }}>
                  {meta[r.trader_id]?.short ?? r.trader_id}
                </span>
              </td>
              <td><span className="sym">{r.symbol.replace(/\.NS$/, "")}</span></td>
              <td><SideBadge side={r.side} /></td>
              <td className="num">{price(r.signal_price)}</td>
              <td className="num">{price(r.fill_price)}</td>
              <td><StatusBadge status={r.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Performance ────────────────────────────────────────────────────────
function NavPanel({ nav }: { nav: AnyDict }) {
  const series = useMemo(
    () =>
      Object.entries(nav)
        .map(([trader, rows]) => {
          const sorted = (rows as AnyDict[]).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
          const first = Number(sorted[0]?.total_equity);
          if (!sorted.length || !first) return null;
          return {
            trader,
            rows: sorted.map((r) => ({
              d: String(r.date).slice(5),
              v: (Number(r.total_equity) / first - 1) * 100,
              equity: Number(r.total_equity),
            })),
            last: sorted[sorted.length - 1],
          };
        })
        .filter((s): s is NonNullable<typeof s> => s !== null && s.rows.length >= 2),
    [nav],
  );

  const latest = Object.entries(nav)
    .map(([trader, rows]) => {
      const sorted = (rows as AnyDict[]).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
      return { trader, row: sorted[sorted.length - 1] };
    })
    .filter((x) => x.row)
    .sort((a, b) => Number(b.row.total_equity) - Number(a.row.total_equity));

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>NAV Performance · cumulative return</h2>
        <div className="legend">
          {series.map((s, i) => (
            <span key={s.trader}>
              <i style={{ background: NAV_COLORS[i % NAV_COLORS.length] }} />
              {s.trader}
            </span>
          ))}
        </div>
        <NavChart series={series} />
      </div>

      <div className="card" style={{ overflowX: "auto" }}>
        <h2>Latest NAV</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Strategy</th>
              <th className="num">Equity</th>
              <th className="num">Cash</th>
              <th className="num">Holdings</th>
              <th className="num">Positions</th>
              <th className="num">Day PnL</th>
              <th className="num">Cumulative PnL</th>
              <th>As of</th>
            </tr>
          </thead>
          <tbody>
            {latest.map(({ trader, row }) => (
              <tr key={trader}>
                <td><span className="sym">{trader}</span></td>
                <td className="num">{inr(row.total_equity)}</td>
                <td className="num">{inr(row.cash)}</td>
                <td className="num">{inr(row.holdings_value)}</td>
                <td className="num">{row.n_positions ?? 0}</td>
                <td className="num"><Pnl v={row.day_pnl_pct} /></td>
                <td className="num"><Pnl v={row.cumulative_pnl_pct} /></td>
                <td className="muted">{fmtDate(row.date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const NAV_COLORS = ["#3ddc97", "#4fd8e0", "#5b8cff", "#9d7bff", "#ff7a8a", "#f6c445"];

function NavChart({ series }: { series: { trader: string; rows: { d: string; v: number }[] }[] }) {
  const W = 1100;
  const H = 250;
  const P = { l: 52, r: 20, t: 18, b: 28 };
  const allV = series.flatMap((s) => s.rows.map((r) => r.v));
  if (!allV.length) return <div className="muted">Not enough NAV history to plot.</div>;
  const min = Math.min(...allV);
  const max = Math.max(...allV);
  const span = max - min || 1;
  const maxLen = Math.max(...series.map((s) => s.rows.length));

  const x = (i: number) => P.l + (i / Math.max(1, maxLen - 1)) * (W - P.l - P.r);
  const y = (v: number) => P.t + (1 - (v - min) / span) * (H - P.t - P.b);
  const ticks = Array.from({ length: 5 }, (_, i) => min + (span * i) / 4);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ overflow: "visible" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="3 3" />
          <text x={P.l - 8} y={y(t) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
            {t >= 0 ? "+" : ""}{t.toFixed(1)}%
          </text>
        </g>
      ))}
      <line x1={P.l} x2={W - P.r} y1={y(0)} y2={y(0)} stroke="var(--border-strong)" strokeWidth={1} />
      {series.map((s, si) => {
        const color = NAV_COLORS[si % NAV_COLORS.length];
        const pts = s.rows.map((r, i) => `${x(i).toFixed(1)},${y(r.v).toFixed(1)}`).join(" ");
        const lastRow = s.rows[s.rows.length - 1];
        return (
          <g key={s.trader}>
            <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={x(s.rows.length - 1)} cy={y(lastRow.v)} r={3} fill={color} />
            <text x={x(s.rows.length - 1) + 6} y={y(lastRow.v) - 6} fontSize="10" fill={color}>
              {s.trader} {lastRow.v >= 0 ? "+" : ""}{lastRow.v.toFixed(1)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}
