"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Journal() {
  const [date, setDate] = useState("");
  const [entry, setEntry] = useState<any>(null);
  const [streak, setStreak] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [e, s] = await Promise.all([
          api("/journal/entry", { date }),
          api("/journal/streak"),
        ]);
        setEntry(e);
        setStreak(s);
      } catch (err: any) {
        setError(err.message);
      }
    })();
  }, [date]);

  return (
    <>
      <h1>Journal</h1>
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <div className="card">
          <h2>Streak</h2>
          <div className="big">{streak?.current_streak ?? streak?.streak ?? "—"} days</div>
        </div>
        <div className="card">
          <h2>Entry</h2>
          <label className="muted">
            Date{" "}
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              style={{ marginLeft: 8 }}
            />
          </label>
          {entry ? (
            <p style={{ whiteSpace: "pre-wrap" }}>
              {String(entry.content ?? entry.text ?? "").slice(0, 2000)}
            </p>
          ) : (
            <div className="muted">No entry for this date.</div>
          )}
        </div>
      </div>
    </>
  );
}
