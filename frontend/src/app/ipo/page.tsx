"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type Ipo = {
  id: string;
  name: string;
  symbol: string;
  exchange: string;
  open_date: string;
  close_date: string;
  listing_date: string;
  price_band: string;
  lot_size: number;
  status: string;
  note: string;
};

const STATUS_COLORS: Record<string, string> = {
  open: "#3ddc97",
  upcoming: "#5b8cff",
  recent: "#f6c445",
  listed: "#4fd8e0",
};

const TABS = [
  { id: "upcoming", label: "Upcoming" },
  { id: "recent", label: "Recent" },
] as const;

export default function Ipo() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("upcoming");
  const [rows, setRows] = useState<Ipo[]>([]);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api<{ ipos: Ipo[]; source?: string }>(`/ipo/${tab}`);
        setRows(res.ipos ?? []);
        setSource(res.source ?? "");
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, [tab]);

  return (
    <>
      <PageHeader
        title="IPOs"
        subtitle="New listings coming to market — track issue windows, price bands and lot sizes before the frenzy starts."
        accent="var(--ipo)"
        accentB="#5b8cff"
      />
      {error && <div className="error">{error}</div>}
      {source === "sample" && (
        <div className="note">
          Sample calendar — no live IPO feed is configured yet. These rows are
          illustrative placeholders so the page stays useful until a real
          source is wired in.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`pill${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {rows.length ? (
        <div className="grid">
          {rows.map((ipo) => {
            const sc = STATUS_COLORS[ipo.status] ?? "#8a93a6";
            return (
              <div key={ipo.id} className="card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <h2 style={{ margin: 0 }}>{ipo.name}</h2>
                  <span className="pill" style={{ borderColor: sc, color: sc }}>
                    {ipo.symbol}
                  </span>
                </div>
                <div className="muted" style={{ marginTop: 4 }}>{ipo.exchange}</div>
                <div className="stat-grid" style={{ marginTop: 10 }}>
                  <div>
                    <div className="stat-label">Open</div>
                    {ipo.open_date}
                  </div>
                  <div>
                    <div className="stat-label">Close</div>
                    {ipo.close_date}
                  </div>
                  <div>
                    <div className="stat-label">Listing</div>
                    {ipo.listing_date}
                  </div>
                  <div>
                    <div className="stat-label">Price band</div>
                    {ipo.price_band}
                  </div>
                  <div>
                    <div className="stat-label">Lot size</div>
                    {ipo.lot_size}
                  </div>
                </div>
                <div style={{ marginTop: 10 }}>
                  <span
                    className="pill-tone"
                    style={{
                      color: sc,
                      background: `color-mix(in srgb, ${sc} 16%, transparent)`,
                      borderColor: `color-mix(in srgb, ${sc} 45%, transparent)`,
                    }}
                  >
                    {ipo.status}
                  </span>
                </div>
                <p className="muted" style={{ marginTop: 10 }}>{ipo.note}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="muted">No {tab} IPOs in the calendar.</div>
      )}
    </>
  );
}
