"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";

export default function Finance() {
  const [tab, setTab] = useState<"portfolio" | "trades" | "signals" | "nav">(
    "portfolio",
  );
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setData(await api(`/finance/${tab}`, { limit: 25 }));
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, [tab]);

  const rows =
    (tab === "portfolio"
      ? data?.holdings ?? data?.securities ?? []
      : data?.trades ?? data?.signals ?? data?.nav ?? []) ?? [];

  return (
    <>
      <h1>Finance</h1>
      {error && <div className="error">{error}</div>}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {(["portfolio", "trades", "signals", "nav"] as const).map((t) => (
          <button
            key={t}
            className="pill"
            style={{
              cursor: "pointer",
              padding: "6px 14px",
              background: tab === t ? "var(--accent)" : "var(--panel)",
              color: tab === t ? "#0f1115" : "var(--text)",
              border: "1px solid var(--border)",
            }}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "portfolio" && data && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="big">
            {data.value ? `₹${Number(data.value).toLocaleString("en-IN")}` : "—"}
          </div>
          <div className="muted">{data.strategy ?? "paper portfolio"}</div>
        </div>
      )}
      {rows.length ? (
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                {Object.keys(rows[0] ?? {}).slice(0, 6).map((k) => (
                  <th key={k}>{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any, i: number) => (
                <tr key={i}>
                  {Object.values(r).slice(0, 6).map((v: any, j: number) => (
                    <td key={j}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
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
