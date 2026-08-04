"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

export default function Calendar() {
  const [birthdays, setBirthdays] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [b, e] = await Promise.all([
          api<Record<string, any>>("/calendar/birthdays"),
          api<Record<string, any>>("/calendar/events"),
        ]);
        setBirthdays(b.birthdays ?? b ?? []);
        setEvents(e.events ?? e ?? []);
      } catch (err: any) {
        setError(err.message);
      }
    })();
  }, []);

  return (
    <>
      <PageHeader
        title="Calendar"
        subtitle="Birthdays and events at a glance — so you never miss the moments that matter."
        accent="var(--calendar)"
        accentB="#3ddc97"
      />
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <div className="card">
          <h2>Birthdays</h2>
          <ul className="list">
            {birthdays.map((b) => (
              <li key={String(b.person_id ?? b.id ?? b.name ?? "birthday")}>
                <span>{b.name}</span>
                <span className="muted">{b.days_until} days</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h2>Events</h2>
          <ul className="list">
            {events.map((e) => (
              <li key={String(e.event_id ?? e.id ?? `${e.date}-${e.title ?? e.name}`)}>
                <span>{e.title ?? e.name}</span>
                <span className="muted">{e.event_date ?? e.date ?? ""}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
