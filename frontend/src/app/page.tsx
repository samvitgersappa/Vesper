"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";

type AnyDict = Record<string, any>;

export default function Dashboard() {
  const [data, setData] = useState<AnyDict>({});
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
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
        setData({ stats, streak, due, readiness, birthdays, portfolio, mood });
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  if (error)
    return <div className="error">Failed to load dashboard: {error}</div>;
  if (!data.stats) return <div className="loading">Loading…</div>;

  const due = Array.isArray(data.due?.due_today)
    ? data.due.due_today
    : data.due?.due_today
      ? [data.due.due_today]
      : [];

  return (
    <>
      <h1>Good day</h1>
      <div className="grid">
        <div className="card">
          <h2>Contacts</h2>
          <div className="big">{data.stats.total_contacts ?? "—"}</div>
          <div className="stat-grid">
            <div>
              <div className="stat-label">Logs</div>
              {data.stats.total_interactions ?? "—"}
            </div>
            <div>
              <div className="stat-label">Due today</div>
              {due.length}
            </div>
          </div>
        </div>
        <div className="card">
          <h2>Journal streak</h2>
          <div className="big">
            {data.streak.current_streak ?? data.streak.streak ?? "—"} days
          </div>
          <div className="muted">mood entries</div>
        </div>
        <div className="card">
          <h2>Study readiness</h2>
          <div className="big">{data.readiness.readiness ?? "—"}%</div>
          <div className="muted">exam preparation</div>
        </div>
        <div className="card">
          <h2>Portfolio value</h2>
          <div className="big">
            {data.portfolio.value
              ? `₹${Number(data.portfolio.value).toLocaleString("en-IN")}`
              : "—"}
          </div>
          <div className="muted">{data.portfolio.strategy ?? "paper"}</div>
        </div>
      </div>

      <div className="grid">
        <div className="card">
          <h2>Upcoming birthdays</h2>
          {Array.isArray(data.birthdays.birthdays) &&
          data.birthdays.birthdays.length ? (
            <ul className="list">
              {data.birthdays.birthdays.slice(0, 6).map((b: AnyDict) => (
                <li key={b.person_id}>
                  <span>{b.name}</span>
                  <span className="muted">{b.days_until} days</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="muted">None in the next 30 days.</div>
          )}
        </div>
        <div className="card">
          <h2>Due today</h2>
          {due.length ? (
            <ul className="list">
              {due.map((p: AnyDict) => (
                <li key={p.person_id}>
                  <span>{p.name}</span>
                  <span className="muted">{p.overdue ? "overdue" : "today"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="muted">Nothing due today.</div>
          )}
        </div>
        <div className="card">
          <h2>Today&apos;s journal</h2>
          {data.mood?.ok ? (
            <>
              <div className="muted">{data.mood.date}</div>
              <p>{String(data.mood.content ?? data.mood.text ?? "").slice(0, 220)}</p>
            </>
          ) : (
            <div className="muted">No entry yet today.</div>
          )}
        </div>
      </div>
    </>
  );
}
