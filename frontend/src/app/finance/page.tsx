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
  { id: "catalyst", label: "Catalyst" },
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
  const [navData, setNavData] = useState<AnyDict | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const n = await api<AnyDict>("/finance/nav");
        setNavData(n);
      } catch {}
    })();
  }, []);

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
      const base = (process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "");
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
            <>
              {navData && Object.keys(navData).length > 1 && (
                <PortfolioNavChart nav={navData} meta={meta} />
              )}
              {traders.map((t) => <HoldingsGroup key={t.trader_id} trader={t} name={meta[t.trader_id]?.name ?? t.trader_id} color={colorFor(t.trader_id)} nav={(navData?.nav ?? navData)?.[t.trader_id]} />)}
            </>
          )}

          {selected === "catalyst_swing" && <CatalystInsights />}
        </>
      )}

      {tab === "nav" && data?.nav && Object.keys(data.nav).length > 0 && <NavPanel nav={data.nav} />}

      {tab === "trades" && (
        <TradesTable rows={(data?.trades ?? []) as TradeRow[]} meta={meta} colorFor={colorFor} />
      )}

      {tab === "signals" && (
        <SignalsTable rows={(data?.signals ?? []) as SignalRow[]} meta={meta} colorFor={colorFor} />
      )}

      {tab === "catalyst" && <CatalystPanel />}
    </>
  );
}

// ── Portfolio: one grouped card per strategy ──────────────────────────
function HoldingsGroup({ trader, name, color, nav }: { trader: Trader; name: string; color: string; nav?: NavRow[] }) {
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
      {nav && nav.length > 1 && (
        <div style={{ height: 48, margin: "0 0 8px 0" }}>
          <SparkLine data={nav} color={color} />
        </div>
      )}
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
type NavRow = { date: string; total_equity: number; cash?: number; holdings_value?: number; n_positions?: number; day_pnl_pct?: number | null; cumulative_pnl_pct?: number | null };

function NavPanel({ nav }: { nav: AnyDict }) {
  const nifty = useMemo(() => (nav.nifty ?? []) as { date: string; cumulative_pct: number }[], [nav]);

  const traderSeries = useMemo(() => {
    return (Object.keys(nav).filter((k) => k !== "nifty") as string[])
      .map((trader) => {
        const rows = ((nav[trader] as NavRow[]) ?? []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
        const first = Number(rows[0]?.total_equity);
        if (!rows.length || !first) return null;
        return {
          trader,
          rows: rows.map((r) => ({
            d: String(r.date),
            v: (Number(r.total_equity) / first - 1) * 100,
            equity: Number(r.total_equity),
          })),
          last: rows[rows.length - 1],
        };
      })
      .filter((s): s is NonNullable<typeof s> => s !== null && s.rows.length >= 1);
  }, [nav]);

  const axes = useMemo(() => {
    const set = new Set<string>();
    for (const s of traderSeries) for (const r of s.rows) set.add(r.d);
    for (const p of nifty) set.add(String(p.date));
    return Array.from(set).sort();
  }, [traderSeries, nifty]);

  const aligned = useMemo(
    () =>
      traderSeries.map((s) => {
        const by = new Map(s.rows.map((r) => [r.d, r.v]));
        return { trader: s.trader, last: s.last, pts: axes.map((d) => by.get(d) ?? null) };
      }),
    [traderSeries, axes],
  );

  const niftyPts = useMemo(() => {
    const by = new Map(nifty.map((p) => [String(p.date), Number(p.cumulative_pct)]));
    return axes.map((d) => by.get(d) ?? null);
  }, [nifty, axes]);

  const latest = Object.entries(nav)
    .filter(([trader]) => trader !== "nifty")
    .map(([trader, rows]) => {
      const sorted = (rows as NavRow[]).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
      return { trader, row: sorted[sorted.length - 1] };
    })
    .filter((x) => x.row)
    .sort((a, b) => Number(b.row.total_equity) - Number(a.row.total_equity));

  const combined: CurveSeries[] = [
    ...aligned.map((s, i) => ({ label: s.trader, color: NAV_COLORS[i % NAV_COLORS.length], pts: s.pts })),
    { label: "NIFTY 50", color: "#b8bec9", dashed: true, pts: niftyPts },
  ];

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>NAV Performance · cumulative return vs NIFTY</h2>
        <p className="muted">Per-strategy equity growth since each book&apos;s first NAV snapshot, overlaid on the NIFTY 50 benchmark (dashed).</p>
        <div className="legend">
          {aligned.map((s, i) => (
            <span key={s.trader}>
              <i style={{ background: NAV_COLORS[i % NAV_COLORS.length] }} />
              {s.trader}
            </span>
          ))}
          <span>
            <i style={{ background: "#b8bec9" }} />
            NIFTY 50
          </span>
        </div>
        <CurveChart axes={axes} series={combined} />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Per-Strategy · vs NIFTY</h2>
        <p className="muted">One chart per strategy; NIFTY 50 benchmark drawn dashed on each.</p>
        <div className="per-trader-grid">
          {aligned.map((s, i) => (
            <div key={s.trader} className="mini-chart">
              <div className="mini-chart-head">
                <span className="sym">{s.trader}</span>
                <Pnl v={s.last.cumulative_pnl_pct} />
              </div>
              <CurveChart
                axes={axes}
                height={140}
                series={[
                  { label: s.trader, color: NAV_COLORS[i % NAV_COLORS.length], pts: s.pts },
                  { label: "NIFTY 50", color: "#b8bec9", dashed: true, pts: niftyPts },
                ]}
              />
            </div>
          ))}
          {aligned.length === 0 && <div className="muted">No NAV history yet.</div>}
        </div>
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

const NAV_COLORS = ["#3ddc97", "#4fd8e0", "#5b8cff", "#9d7bff", "#ff7a8a", "#f6c445", "#ff9f43"];

type CurveSeries = { label: string; color: string; dashed?: boolean; pts: (number | null)[] };

function CurveChart({ axes, series, height = 250 }: { axes: string[]; series: CurveSeries[]; height?: number }) {
  const W = 1100;
  const H = height;
  const P = { l: 52, r: 150, t: 18, b: 28 };
  const allV = series.flatMap((s) => s.pts.filter((v): v is number => v != null));
  if (!allV.length || !axes.length) return <div className="muted">Not enough history to plot.</div>;
  const min = Math.min(...allV, 0);
  const max = Math.max(...allV, 0);
  const span = max - min || 1;
  const x = (i: number) => P.l + (i / Math.max(1, axes.length - 1)) * (W - P.l - P.r);
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
      {series.map((s) => {
        const pts = s.pts
          .map((v, i) => (v == null ? null : ({ px: x(i), py: y(v), v } as const)))
          .filter((p): p is NonNullable<typeof p> => p !== null);
        if (!pts.length) return null;
        const line = pts.map((p) => `${p.px.toFixed(1)},${p.py.toFixed(1)}`).join(" ");
        const last = pts[pts.length - 1];
        return (
          <g key={s.label}>
            <polyline points={line} fill="none" stroke={s.color} strokeWidth={s.dashed ? 1.5 : 2} strokeDasharray={s.dashed ? "5 4" : undefined} strokeLinejoin="round" strokeLinecap="round" />
            {!s.dashed && <circle cx={last.px} cy={last.py} r={3} fill={s.color} />}
            {!s.dashed && (
              <text x={last.px + 6} y={last.py - 6} fontSize="10" fill={s.color}>
                {s.label} {last.v >= 0 ? "+" : ""}{last.v.toFixed(1)}%
              </text>
            )}
          </g>
        );
      })}
      <text x={P.l} y={H - 8} fontSize="10" fill="var(--muted)">{axes[0]}</text>
      <text x={W - P.r} y={H - 8} textAnchor="end" fontSize="10" fill="var(--muted)">{axes[axes.length - 1]}</text>
    </svg>
  );
}

// ── Catalyst Swing Trader (Trader 6) ────────────────────────────────────
type CatalystScore = {
  symbol: string;
  sector?: string;
  composite_score?: number;
  rank?: number;
  catalyst_signal?: string | null;
  llm_analyzed?: boolean;
  verdict?: { signal?: string; urgency?: number; confidence?: number; rationale?: string };
};

type CatalystPosition = {
  symbol: string;
  entry_date: string;
  entry_price?: number;
  qty: number;
  atr?: number;
  stop_loss?: number;
  trailing_stop?: number;
  target?: number;
  days_held?: number;
  last_price?: number;
  avg_price?: number;
};

type NewsRow = {
  symbol: string;
  title: string;
  source?: string;
  url?: string;
  published_at?: string;
};

type CatalystTrade = {
  trader_id: string;
  date: string;
  symbol: string;
  side: string;
  qty: number;
  signal_price?: number;
  fill_price?: number;
  realized_pnl?: number;
};

function SignalBadge({ signal }: { signal?: string | null }) {
  const s = String(signal ?? "none");
  const cls = s === "positive" ? "buy" : s === "negative" ? "sell" : "pending";
  return <span className={`badge ${cls}`}>{s}</span>;
}

function CatalystPanel() {
  const [scores, setScores] = useState<CatalystScore[]>([]);
  const [positions, setPositions] = useState<CatalystPosition[]>([]);
  const [news, setNews] = useState<NewsRow[]>([]);
  const [budget, setBudget] = useState<AnyDict[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setError("");
      try {
        const [sc, pos, nw, us] = await Promise.all([
          api<{ scores: CatalystScore[] }>("/finance/catalyst/scores", { limit: 50 }),
          api<{ positions: CatalystPosition[] }>("/finance/catalyst/positions"),
          api<{ news: NewsRow[] }>("/finance/catalyst/news", { limit: 100 }),
          api<{ budget: AnyDict[] }>("/finance/catalyst/usage"),
        ]);
        if (cancelled) return;
        setScores(sc.scores ?? []);
        setPositions(pos.positions ?? []);
        setNews(nw.news ?? []);
        setBudget(us.budget ?? []);
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
  }, []);

  const budgetToday = budget[0]?.calls_used ?? 0;

  return (
    <>
      <div className="stat-cards">
        <div className="stat-card">
          <span className="stat-label">Universe</span>
          <div className="stat-num" style={{ color: "var(--finance)" }}>{scores.length}</div>
          <div className="stat-sub">factor-composite funnel</div>
        </div>
        <div className="stat-card">
          <span className="stat-label">Open Positions</span>
          <div className="stat-num">{positions.length}</div>
          <div className="stat-sub">swing book · max 8</div>
        </div>
        <div className="stat-card">
          <span className="stat-label">LLM Calls Today</span>
          <div className="stat-num">{budgetToday}</div>
          <div className="stat-sub">daily budget · capped at 65</div>
        </div>
        <div className="stat-card">
          <span className="stat-label">News Captured</span>
          <div className="stat-num">{news.length}</div>
          <div className="stat-sub">headlines across the funnel</div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {positions.length > 0 && (
        <div className="card" style={{ marginBottom: 16, overflowX: "auto" }}>
          <h2>Open Swing Positions</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Last</th>
                <th className="num">Stop</th>
                <th className="num">Trailing</th>
                <th className="num">Target</th>
                <th className="num">Days</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.symbol}>
                  <td><span className="sym">{p.symbol.replace(/\.NS$/, "")}</span></td>
                  <td className="num">{p.qty.toLocaleString("en-IN")}</td>
                  <td className="num">{price(p.entry_price)}</td>
                  <td className="num">{price(p.last_price)}</td>
                  <td className="num">{price(p.stop_loss)}</td>
                  <td className="num">{price(p.trailing_stop)}</td>
                  <td className="num">{price(p.target)}</td>
                  <td className="num">{p.days_held ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CatalystInsights />
    </>
  );
}

// Self-contained catalyst news + LLM verdicts + recent trades. Rendered on the
// Catalyst tab and, when Catalyst is the filtered strategy, on the Portfolio tab.
function CatalystInsights() {
  const [scores, setScores] = useState<CatalystScore[]>([]);
  const [news, setNews] = useState<NewsRow[]>([]);
  const [trades, setTrades] = useState<CatalystTrade[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setError("");
      try {
        const [sc, nw, tr] = await Promise.all([
          api<{ scores: CatalystScore[] }>("/finance/catalyst/scores", { limit: 50 }),
          api<{ news: NewsRow[] }>("/finance/catalyst/news", { limit: 100 }),
          api<{ trades: CatalystTrade[] }>("/finance/trades", { strategy: "catalyst_swing", limit: 20 }),
        ]);
        if (cancelled) return;
        setScores(sc.scores ?? []);
        setNews(nw.news ?? []);
        setTrades(tr.trades ?? []);
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
  }, []);

  const newsBySymbol = useMemo(() => {
    const m: Record<string, NewsRow[]> = {};
    for (const n of news) {
      (m[n.symbol] = m[n.symbol] ?? []).push(n);
    }
    return m;
  }, [news]);

  return (
    <>
      {error && <div className="error">{error}</div>}

      {trades.length > 0 && (
        <div className="card" style={{ marginBottom: 16, overflowX: "auto" }}>
          <h2>Recent Catalyst Trades</h2>
          <p className="muted">Executed buy/sell history for the swing book (newest first).</p>
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th className="num">Signal</th>
                <th className="num">Fill</th>
                <th className="num">Realized PnL</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i}>
                  <td className="muted">{fmtDate(t.date)}</td>
                  <td><span className="sym">{t.symbol.replace(/\.NS$/, "")}</span></td>
                  <td><SideBadge side={t.side} /></td>
                  <td className="num">{t.qty.toLocaleString("en-IN")}</td>
                  <td className="num">{price(t.signal_price)}</td>
                  <td className="num">{price(t.fill_price)}</td>
                  <td className="num"><Pnl v={t.realized_pnl} abs /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card" style={{ overflowX: "auto" }}>
        <h2>Screen · LLM Catalyst Verdicts</h2>
        <p className="muted">
          Per-stock factor composite, the LLM catalyst verdict (grounded in the news below), and the news headlines the verdict was based on.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Symbol</th>
              <th>Sector</th>
              <th className="num">Composite</th>
              <th>Signal</th>
              <th className="num">Conf</th>
              <th className="num">Urg</th>
              <th>Rationale</th>
              <th>News</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((s) => {
              const symNews = newsBySymbol[s.symbol] ?? [];
              return (
                <tr key={s.symbol}>
                  <td className="muted">{s.rank ?? ""}</td>
                  <td><span className="sym">{s.symbol.replace(/\.NS$/, "")}</span></td>
                  <td className="muted wrap sec-cell">{s.sector}</td>
                  <td className="num">{s.composite_score != null ? s.composite_score.toFixed(3) : "—"}</td>
                  <td><SignalBadge signal={s.catalyst_signal ?? s.verdict?.signal} /></td>
                  <td className="num">{s.verdict?.confidence != null ? `${(s.verdict.confidence * 100).toFixed(0)}%` : "—"}</td>
                  <td className="num">{s.verdict?.urgency != null ? `${(s.verdict.urgency * 100).toFixed(0)}%` : "—"}</td>
                  <td className="muted wrap rat-cell">{s.verdict?.rationale}</td>
                  <td className="wrap news-cell">
                    {symNews.length === 0 ? (
                      <span className="muted">—</span>
                    ) : (
                      <div className="news-stack">
                        {symNews.slice(0, 3).map((n, i) => (
                          <div key={i} className="news-item">
                            <a className="news-title" href={n.url} target="_blank" rel="noreferrer" title={n.title}>
                              {n.title}
                            </a>
                            {n.source && <span className="news-src">{n.source}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {scores.length === 0 && <div className="muted" style={{ padding: 16 }}>No screen data yet — run the 18:20 catalyst_screen job.</div>}
      </div>
    </>
  );
}

// ── Sparkline (per-trader NAV mini-chart) ─────────────────────────────
function SparkLine({ data, color }: { data: NavRow[]; color: string }) {
  const pts = data.map(d => d.total_equity).filter(v => v != null && !isNaN(v)) as number[];
  if (pts.length < 2) return null;
  const min = Math.min(...pts), max = Math.max(...pts), range = max - min || 1;
  const w = pts.length * 3 + 2, h = 48;
  const x = (i: number) => 1 + (i / Math.max(1, pts.length - 1)) * (w - 2);
  const y = (v: number) => h - 4 - ((v - min) / range) * (h - 8);
  const poly = pts.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" style={{overflow:"visible"}} preserveAspectRatio="none">
    <polyline points={poly} fill="none" stroke={color} strokeWidth={1} strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}

// ── Portfolio NAV chart (total equity over time, all traders + Nifty) ──
function PortfolioNavChart({ nav, meta }: { nav: AnyDict; meta: Record<string,any> }) {
  const navObj = nav.nav || nav;
  const traders = Object.keys(navObj).filter(k => k !== 'nifty');
  if (traders.length < 2) return null;
  const firstRows = navObj[traders[0]] as any[] | undefined;
  if (!firstRows) return null;
  const dates = firstRows.map((r: any) => String(r.date));
  if (dates.length < 2) return null;
  const niftyRaw = (nav.nifty || []) as {date:string;close:number;cumulative_pct:number}[];
  const niftyMap = new Map(niftyRaw.map(r => [String(r.date), r.cumulative_pct] as [string, number]));
  const series: CurveSeries[] = [];
  for (let i = 0; i < traders.length; i++) {
    const t = traders[i];
    const rows = navObj[t] as NavRow[] | undefined;
    if (!rows || rows.length < 2) continue;
    const eq = rows.map(r => Number(r.total_equity));
    let base: number = 1;
    for (const v of eq) { if (!isNaN(v) && v > 0) { base = v; break; } }
    series.push({
      label: meta[t]?.short || t,
      color: NAV_COLORS[i % NAV_COLORS.length],
      pts: eq.map(v => !isNaN(v) ? (v / base - 1) * 100 : null),
    });
  }
  if (niftyMap.size > 0) {
    series.push({
      label: "NIFTY 50", color: "#b8bec9", dashed: true,
      pts: dates.map(d => { const v = niftyMap.get(d); return v !== undefined ? v : null; }),
    });
  }
  return <div className="card" style={{marginBottom:16}}>
    <h2>Portfolio Value Over Time</h2>
    <div className="legend" style={{marginBottom:8}}>
      {series.map(s => <span key={s.label}><i style={{background:s.color,border:s.dashed?'1px dashed '+s.color:'none'}}/>{s.label}</span>)}
    </div>
    <CurveChart axes={dates} series={series} height={200} />
  </div>;
}
