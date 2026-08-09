"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import LiveActivity from "../components/LiveActivity";

type AnyDict = Record<string, any>;

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Burning the midnight oil";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  if (h < 21) return "Good evening";
  return "Winding down";
}

const CARD_ACCENTS: Record<string, { a: string; b: string; ico: string }> = {
  contacts: { a: "#ff7a8a", b: "#ff9d6b", ico: "👥" },
  streak: { a: "#f6c445", b: "#f0a84b", ico: "🔥" },
  study: { a: "#5b8cff", b: "#9d7bff", ico: "📚" },
  portfolio: { a: "#3ddc97", b: "#4fd8e0", ico: "📈" },
};

export default function Dashboard() {
  const [data, setData] = useState<AnyDict>({});
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [stats, streak, due, readiness, birthdays, portfolio, mood] =
          await Promise.all([
            api("/relationship/stats"),
            api("/journal/streak"),
            api("/relationship/due-today"),
            api("/study/readiness"),
            api("/calendar/birthdays"),
            api("/finance/portfolio"),
            api("/journal/entry"),
          ]);
        if (cancelled) return;
        setData({ stats, streak, due, readiness, birthdays, portfolio, mood });
      } catch (e: any) {
        if (!cancelled) setError(e.message);
      }
    };
    load();
    const id = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error)
    return <div className="error">Failed to load dashboard: {error}</div>;
  if (!data.stats) return <div className="loading">Loading…</div>;

  const due = Array.isArray(data.due?.overdue)
    ? data.due.overdue
    : data.due?.overdue
      ? [data.due.overdue]
      : [];

  const totalPortfolio =
    Array.isArray(data.portfolio?.traders)
      ? data.portfolio.traders.reduce(
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
      : null;

  const readinessPct =
    data.readiness?.readiness && data.readiness.readiness !== "no_data"
      ? data.readiness.readiness
      : null;

  const today = new Date().toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const kpi = (key: string, label: string, value: React.ReactNode, sub?: string) => {
    const c = CARD_ACCENTS[key] ?? CARD_ACCENTS.contacts;
    return (
      <div className="card" key={key}>
        <h2>
          <span className="card-ico" style={{ background: `color-mix(in srgb, ${c.a} 22%, transparent)` }}>
            {c.ico}
          </span>
          {label}
        </h2>
        <div className="big grad" style={{ "--big-a": c.a, "--big-b": c.b } as React.CSSProperties}>
          {value}
        </div>
        {sub && <div className="muted" style={{ marginTop: 4 }}>{sub}</div>}
      </div>
    );
  };

  return (
    <>
      <section className="hero">
        <h1>{greeting()}</h1>
        <p className="date-line">{today} · Vesper command center</p>
        <p className="hero-note"><span className="live-dot" /> A quiet overview of what deserves your attention next.</p>
        <div className="hero-stats">
          <div className="hero-stat">
            <span className="stat-num" style={{ color: "var(--people)" }}>
              {data.stats.total_contacts ?? "—"}
            </span>
            <span className="stat-label">Contacts</span>
          </div>
          <div className="hero-stat">
            <span className="stat-num" style={{ color: "var(--journal)" }}>
              {data.streak.current_streak ?? data.streak.streak ?? "—"}
            </span>
            <span className="stat-label">Day streak</span>
          </div>
          <div className="hero-stat">
            <span className="stat-num" style={{ color: "var(--study)" }}>
              {readinessPct ? `${readinessPct}%` : "—"}
            </span>
            <span className="stat-label">Exam ready</span>
          </div>
          <div className="hero-stat">
            <span className="stat-num" style={{ color: "var(--finance)" }}>
              {totalPortfolio
                ? `₹${Number(totalPortfolio / 100000).toLocaleString("en-IN", { maximumFractionDigits: 1 })}L`
                : "—"}
            </span>
            <span className="stat-label">Portfolio</span>
          </div>
        </div>
      </section>

      <div className="section-intro"><div><h2>Signals at a glance</h2><p>The few numbers worth carrying into the day.</p></div><span className="muted">refreshes every 30s</span></div>
      <div className="grid">
        {kpi("contacts", "Relationships", data.stats.total_contacts ?? "—", `${data.stats.total_interactions ?? 0} logs · ${due.length} due`)}
        {kpi("streak", "Journal Streak", `${data.streak.current_streak ?? data.streak.streak ?? 0}d`, "mood entries")}
        {kpi("study", "Exam Readiness", readinessPct ? `${readinessPct}%` : "—", data.readiness?.message ?? "no exams scheduled")}
        {kpi("portfolio", "Portfolio Value", totalPortfolio ? `₹${Number(totalPortfolio).toLocaleString("en-IN")}` : "—", `${data.portfolio?.traders?.length ?? 0} paper strategies`)}
      </div>

      <div className="section-intro"><div><h2>Open loops</h2><p>Small things that become important when ignored.</p></div></div>
      <div className="grid">
        <div className="card">
          <h2>Due Today</h2>
          {due.length ? (
            <ul className="list">
              {due.map((p: AnyDict) => (
                <li key={p.id ?? p.person_id}>
                  <span>{p.name}</span>
                  <span className={p.days_overdue ? "bad" : "warn"}>
                    {p.days_overdue ? `${p.days_overdue}d overdue` : "today"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="data-empty"><div><strong>Clean slate</strong><span>Nothing due today.</span></div></div>
          )}
        </div>

        <div className="card">
          <h2>Upcoming Birthdays</h2>
          {Array.isArray(data.birthdays?.birthdays) &&
          data.birthdays.birthdays.length ? (
            <ul className="list">
              {data.birthdays.birthdays.slice(0, 6).map((b: AnyDict) => (
                <li key={b.person_id}>
                  <span>{b.name}</span>
                  <span className="muted">{b.days_until}d away</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="data-empty"><div><strong>No birthdays queued</strong><span>Nothing in the next 30 days.</span></div></div>
          )}
        </div>

        <div className="card">
          <h2>Today&apos;s Journal</h2>
          {data.mood?.found ? (
            <>
              <div className="muted">{data.mood.date}</div>
              <p>{String(data.mood.content ?? data.mood.text ?? "").slice(0, 200)}</p>
            </>
          ) : (
            <div className="data-empty"><div><strong>Blank page</strong><span>Capture a thought to begin today.</span></div></div>
          )}
        </div>
      </div>

      <LiveActivity />
    </>
  );
}
