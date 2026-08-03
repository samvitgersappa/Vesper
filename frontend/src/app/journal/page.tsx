"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

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
      <PageHeader
        title="Journal"
        subtitle="A running diary of how your days actually go — write, reflect, and keep the streak alive."
        accent="var(--journal)"
        accentB="#f0a84b"
      />
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <div className="card">
          <h2>Streak</h2>
          <div className="big grad" style={{ "--big-a": "#f6c445", "--big-b": "#f0a84b" } as React.CSSProperties}>
            {streak?.current_streak ?? streak?.streak ?? "—"} days
          </div>
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
        <div className="card" style={{ gridColumn: "1 / -1" }}>
          <h2>
            <span className="card-ico" style={{ background: "color-mix(in srgb, var(--graph) 22%, transparent)" }}>
              🧠
            </span>
            Second Brain
          </h2>
          <p className="muted">
            Every journal entry, capture and knowledge note lives as a file in
            your Obsidian vault. The private Quartz garden turns that vault into
            a browsable site — full-text search, wikilinks, backlinks and an
            interactive graph — served only on your tailnet.
          </p>
          <a
            className="btn"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              marginTop: 8,
              padding: "10px 18px",
              borderRadius: 12,
              color: "#fff",
              fontWeight: 650,
              textDecoration: "none",
              background: "linear-gradient(120deg, #b980f7, #5b8cff)",
            }}
            href="/brain/"
          >
            Open the Garden →
          </a>
        </div>
      </div>
    </>
  );
}
