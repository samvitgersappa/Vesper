"use client";

import { useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type JournalDay = {
  date: string;
  has_entry: boolean;
  mood?: string | null;
  complete: boolean;
  word_count: number;
};

export default function Journal() {
  const [date, setDate] = useState("");
  const [entry, setEntry] = useState<any>(null);
  const [streak, setStreak] = useState<any>(null);
  const [days, setDays] = useState<JournalDay[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([api(`/journal/entry`, { date }), api(`/journal/streak`), api(`/journal/calendar`)]).then(
      ([entryResult, streakResult, calendarResult]: any[]) => {
        if (!active) return;
        setEntry(entryResult);
        setStreak(streakResult);
        setDays(calendarResult.days ?? []);
      },
    ).catch((err: Error) => active && setError(err.message));
    return () => { active = false; };
  }, [date]);

  const activeDays = useMemo(() => days.filter((day) => day.has_entry).length, [days]);
  const weeks = useMemo(() => {
    const padded = [...days];
    while (padded.length && new Date(`${padded[0].date}T00:00:00`).getDay() !== 0) padded.unshift({ date: "", has_entry: false, complete: false, word_count: 0 });
    return Array.from({ length: Math.ceil(padded.length / 7) }, (_, i) => padded.slice(i * 7, i * 7 + 7));
  }, [days]);

  return (
    <>
      <PageHeader title="Journal" subtitle="A calm place to notice the shape of your days, one honest entry at a time." accent="var(--journal)" accentB="#f0a84b" />
      {error && <div className="error">{error}</div>}

      <section className="journal-hero">
        <div>
          <span className="eyebrow">Daily practice</span>
          <h1>Keep the thread.</h1>
          <p>Small entries compound into a record you can actually return to.</p>
        </div>
        <div className="journal-hero-stats">
          <div><strong>{streak?.current_streak ?? streak?.streak ?? 0}</strong><span>day streak</span></div>
          <div><strong>{activeDays}</strong><span>active days</span></div>
        </div>
      </section>

      <div className="journal-layout">
        <div className="card journal-calendar-card">
          <div className="journal-card-head"><div><span className="eyebrow">Last 12 weeks</span><h2>Consistency calendar</h2></div><span className="muted">{activeDays} of {days.length} days</span></div>
          <div className="weekday-row">{["S", "M", "T", "W", "T", "F", "S"].map((day, i) => <span key={`${day}-${i}`}>{day}</span>)}</div>
          <div className="streak-calendar" aria-label="Journal activity calendar">
            {weeks.flat().map((day, index) => day.date ? (
              <button key={day.date} className={`streak-day ${day.has_entry ? "has-entry" : ""} ${day.complete ? "complete" : ""} ${day.date === date ? "selected" : ""}`} title={`${day.date}${day.mood ? ` · ${day.mood}` : ""}`} onClick={() => setDate(day.date)}>{day.mood || ""}</button>
            ) : <span className="streak-day empty" key={`empty-${index}`} />)}
          </div>
          <div className="calendar-legend"><span><i className="legend-dot" />entry</span><span><i className="legend-dot complete" />complete</span><span className="muted">Click a day to open it</span></div>
        </div>

        <div className="card journal-entry-card">
          <div className="journal-card-head"><div><span className="eyebrow">Read back</span><h2>{date ? fmtDate(date) : "Today"}</h2></div><input aria-label="Choose journal date" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></div>
          {entry?.found ? <article className="journal-entry-content">{String(entry.content ?? entry.text ?? "").slice(0, 5000)}</article> : <div className="empty-state"><span className="empty-mark">✦</span><strong>No entry here yet</strong><p>Write a few lines in Hermes or the journal tool and this day will appear in your calendar.</p></div>}
        </div>
      </div>

      <div className="card garden-card"><div><span className="eyebrow">Second brain</span><h2>Your garden is growing</h2><p className="muted">Journal entries, captures, and knowledge notes stay browsable in the private Obsidian garden.</p></div><a className="btn" href="/brain/">Open the Garden <span>↗</span></a></div>
    </>
  );
}
