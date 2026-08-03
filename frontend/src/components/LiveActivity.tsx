"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Item = {
  ts?: string | null;
  kind: string;
  domain: string;
  detail: string;
  label?: string;
  ok?: boolean | null;
};

const KIND_LABEL: Record<string, string> = {
  hermes_tool: "tool call",
  capture: "captured",
  automation: "automation",
  diary: "journal",
  spending: "spent",
  workout: "workout",
  person: "person",
  interaction: "interaction",
  trade: "trade",
  nav: "nav",
  graph: "graph",
  test: "test",
};

function fmtAgo(ts?: string | null): string {
  if (!ts) return "";
  const t = new Date(ts.endsWith("Z") || ts.includes("+") ? ts : ts + "Z").getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const DOMAIN_COLOR: Record<string, string> = {
  hermes: "#5b8cff",
  knowledge: "#b980f7",
  automation: "#f6c445",
  relationships: "#ff7a8a",
  journal: "#f6c445",
  finance: "#3ddc97",
  graph: "#b980f7",
  study: "#5b8cff",
};

export default function LiveActivity() {
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api<{ items: Item[] }>("/activity/recent", { limit: 40 });
        if (cancelled) return;
        setItems(res.items ?? []);
        setLive(true);
        setError("");
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message);
          setLive(false);
        }
      }
    };
    load();
    const id = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="card" style={{ gridColumn: "1 / -1" }}>
      <h2>
        <span className="live-dot" />
        Live Activity
        <span className="muted" style={{ fontWeight: 400 }}>
          — everything the system has written, streaming every 15s
        </span>
      </h2>
      {error && <div className="error">{error}</div>}
      {!items.length && !error && (
        <div className="muted">
          No activity yet — when Hermes calls tools, captures notes, or the
          automation engine runs jobs, they appear here in real time.
        </div>
      )}
      <ul className="feed">
        {items.map((it, i) => {
          const color = DOMAIN_COLOR[it.domain] ?? "#8a93a6";
          return (
            <li key={i}>
              <span className="feed-dot" style={{ background: color, boxShadow: `0 0 10px ${color}` }} />
              <div className="feed-body">
                <div>
                  <span style={{ color }}>
                    {it.domain}
                  </span>{" "}
                  <span className="muted">{KIND_LABEL[it.kind] ?? it.kind}</span>
                </div>
                <div className="feed-detail">
                  {it.detail}
                  {it.label ? <span className="muted"> {it.label}</span> : null}
                  {it.ok != null && (
                    <span className={it.ok ? "good" : "bad"}>{it.ok ? " ✓" : " ✗"}</span>
                  )}
                </div>
              </div>
              <span className="muted feed-ago">{fmtAgo(it.ts)}</span>
            </li>
          );
        })}
      </ul>
      <div className="muted" style={{ marginTop: 8 }}>
        {live ? "● live" : "○ offline"}
      </div>
    </div>
  );
}
