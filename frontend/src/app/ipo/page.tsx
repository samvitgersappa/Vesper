"use client";

import { useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type Ipo = { id: string; name: string; symbol: string; exchange: string; open_date: string; close_date: string; listing_date: string; price_band: string; lot_size: number; status: string; note: string; source_url?: string };
const TABS = [{ id: "all", label: "All issues" }, { id: "upcoming", label: "Upcoming" }, { id: "recent", label: "Recent" }] as const;
const STATUS: Record<string, { label: string; color: string }> = { open: { label: "Open now", color: "#3ddc97" }, upcoming: { label: "Upcoming", color: "#5b8cff" }, recent: { label: "Closed", color: "#f6c445" }, listed: { label: "Listed", color: "#4fd8e0" }, draft: { label: "Draft", color: "#8a93a6" } };

function parseUpperBand(band: string) { const values = (band || "").match(/[\d,]+/g)?.map((v) => Number(v.replace(/,/g, ""))) ?? []; return values.length ? Math.max(...values) : 0; }
function daysUntil(value?: string) { if (!value) return null; return Math.ceil((new Date(`${value}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86400000); }

export default function Ipo() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("all");
  const [rows, setRows] = useState<Ipo[]>([]);
  const [source, setSource] = useState("");
  const [query, setQuery] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { let cancelled = false; api<{ ipos: Ipo[]; source?: string }>(`/ipo/${tab}`).then((res) => { if (!cancelled) { setRows(res.ipos ?? []); setSource(res.source ?? ""); } }).catch((e: any) => { if (!cancelled) setError(e.message); }); return () => { cancelled = true; }; }, [tab]);
  const visible = useMemo(() => rows.filter((ipo) => (!query || `${ipo.name} ${ipo.symbol} ${ipo.exchange}`.toLowerCase().includes(query.toLowerCase())) && (!onlyOpen || ipo.status === "open")), [rows, query, onlyOpen]);
  const openCount = rows.filter((r) => r.status === "open").length;
  const next = rows.filter((r) => r.open_date && (daysUntil(r.open_date) ?? -1) >= 0).sort((a, b) => a.open_date.localeCompare(b.open_date))[0];

  return <>
    <PageHeader title="IPO Radar" subtitle="A decision-ready view of Indian primary-market issues: what is open, what is next, and which dates matter." accent="var(--ipo)" accentB="#5b8cff" />
    {error && <div className="error">{error}</div>}
    <section className="ipo-banner"><div><span className="eyebrow">Primary market watch</span><h2>{openCount ? `${openCount} issue${openCount === 1 ? "" : "s"} open now` : next ? `${next.name} opens ${fmtDate(next.open_date)}` : "No dated issues ahead"}</h2><p>Open/close windows and listing milestones, with source transparency when details are unavailable.</p></div><div className="ipo-source"><strong className={source === "live" ? "good" : "warn"}>{source === "live" ? "● live calendar" : source === "sample" ? "○ fallback data" : "○ unavailable"}</strong><small>{source === "live" ? "Moneycontrol or Chittorgarh" : "Check the source before acting"}</small></div></section>
    <div className="ipo-summary"><div><strong>{rows.length}</strong><span>{tab === "all" ? "issues in feed" : `${tab} issues`}</span></div><div><strong className="good">{openCount}</strong><span>open for subscription</span></div><div><strong>{rows.filter((r) => r.listing_date).length}</strong><span>with listing date</span></div><div><strong>{rows.filter((r) => r.price_band).length}</strong><span>with price band</span></div></div>
    <div className="ipo-controls"><div className="people-search"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search company or symbol…" /></div><div className="ipo-tabs">{TABS.map((t) => <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>{t.label}</button>)}<button className={onlyOpen ? "active" : ""} onClick={() => setOnlyOpen((v) => !v)}>Open only</button></div></div>
    {source === "sample" && <div className="note">The primary feed is unavailable and the fallback is clearly marked. Do not use fallback rows as confirmed investment information.</div>}
    {visible.length ? <div className="ipo-list">{visible.map((ipo) => <IpoCard key={ipo.id} ipo={ipo} />)}</div> : <div className="data-empty"><div><strong>No issues match</strong><span>Try another search or turn off Open only.</span></div></div>}
  </>;
}

function IpoCard({ ipo }: { ipo: Ipo }) {
  const state = STATUS[ipo.status] ?? STATUS.upcoming;
  const openingIn = daysUntil(ipo.open_date);
  const closingIn = daysUntil(ipo.close_date);
  const upper = parseUpperBand(ipo.price_band);
  const application = upper && ipo.lot_size ? upper * ipo.lot_size : 0;
  return <article className="ipo-row"><div className="ipo-row-main"><div className="ipo-company-mark" style={{ color: state.color, borderColor: `color-mix(in srgb, ${state.color} 45%, transparent)` }}>{ipo.symbol?.slice(0, 3) || "IPO"}</div><div className="ipo-company"><div><h3>{ipo.name}</h3><span>{ipo.exchange} · {ipo.symbol || "Symbol pending"}</span></div><span className="ipo-status" style={{ color: state.color, background: `color-mix(in srgb, ${state.color} 13%, transparent)` }}>{state.label}</span></div></div><div className="ipo-dates"><div><small>Opens</small><strong>{fmtDate(ipo.open_date)}</strong>{openingIn !== null && <em>{openingIn < 0 ? `${Math.abs(openingIn)}d ago` : openingIn === 0 ? "today" : `in ${openingIn}d`}</em>}</div><div><small>Closes</small><strong>{fmtDate(ipo.close_date)}</strong>{closingIn !== null && <em>{closingIn < 0 ? "closed" : closingIn === 0 ? "today" : `in ${closingIn}d`}</em>}</div><div><small>Listing</small><strong>{fmtDate(ipo.listing_date)}</strong></div></div><div className="ipo-facts"><div><small>Price band</small><strong>{ipo.price_band || "Not published"}</strong></div><div><small>Lot size</small><strong>{ipo.lot_size || "Not published"}</strong></div><div><small>Max lot cost</small><strong>{application ? `₹${application.toLocaleString("en-IN")}` : "Not published"}</strong></div></div><p>{ipo.note}</p>{ipo.source_url && <a href={ipo.source_url} target="_blank" rel="noreferrer">Open source detail ↗</a>}</article>;
}
