"use client";

import { useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type CalendarEvent = { date: string; type: string; title: string; source?: string };
const EVENT_TYPES = ["birthday", "interaction", "reminder", "life_event", "exam"];
const TYPE_META: Record<string, { label: string; color: string; icon: string }> = { birthday: { label: "Birthday", color: "#ff7a8a", icon: "♥" }, interaction: { label: "Interaction", color: "#b980f7", icon: "↗" }, reminder: { label: "Reminder", color: "#f6c445", icon: "!" }, life_event: { label: "Life event", color: "#3ddc97", icon: "✦" }, exam: { label: "Exam", color: "#5b8cff", icon: "◆" } };

function isoDate(date: Date) { return date.toISOString().slice(0, 10); }
function monthStart(value: Date) { return new Date(value.getFullYear(), value.getMonth(), 1); }
function monthEnd(value: Date) { return new Date(value.getFullYear(), value.getMonth() + 1, 0); }
function monthLabel(value: Date) { return value.toLocaleDateString(undefined, { month: "long", year: "numeric" }); }
function dateLabel(value: string) { return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }); }

export default function Calendar() {
  const [month, setMonth] = useState(() => monthStart(new Date()));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [birthdays, setBirthdays] = useState<any[]>([]);
  const [selectedDate, setSelectedDate] = useState(isoDate(new Date()));
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set(EVENT_TYPES));
  const [error, setError] = useState("");

  useEffect(() => {
    const start = monthStart(month); const end = monthEnd(month);
    Promise.all([api<Record<string, any>>("/calendar/events", { from_date: isoDate(start), to_date: isoDate(end) }), api<Record<string, any>>("/calendar/birthdays")]).then(([calendar, birthdayData]) => { setEvents(calendar.events ?? []); setBirthdays(birthdayData.birthdays ?? []); if (selectedDate < isoDate(start) || selectedDate > isoDate(end)) setSelectedDate(isoDate(start)); }).catch((e: any) => setError(e.message));
  }, [month]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleEvents = useMemo(() => events.filter((event) => activeTypes.has(event.type)), [events, activeTypes]);
  const byDate = useMemo(() => visibleEvents.reduce<Record<string, CalendarEvent[]>>((result, event) => { (result[event.date] ??= []).push(event); return result; }, {}), [visibleEvents]);
  const selectedEvents = byDate[selectedDate] ?? [];
  const days = useMemo(() => { const start = monthStart(month); const firstDay = start.getDay(); const total = monthEnd(month).getDate(); return Array.from({ length: Math.ceil((firstDay + total) / 7) * 7 }, (_, index) => { const day = index - firstDay + 1; return day < 1 || day > total ? null : new Date(month.getFullYear(), month.getMonth(), day); }); }, [month]);
  const toggleType = (type: string) => setActiveTypes((current) => { const next = new Set(current); if (next.has(type)) next.delete(type); else next.add(type); return next; });
  const todayKey = isoDate(new Date());

  return <>
    <PageHeader title="Calendar OS" subtitle="A practical view of the commitments, people, and deadlines that deserve a place on your day." accent="var(--calendar)" accentB="#3ddc97" />
    {error && <div className="error">{error}</div>}
    <section className="calendar-banner"><div className="calendar-orbit">◌</div><div><span className="eyebrow">One month at a time</span><h2>{visibleEvents.length} moments in {monthLabel(month)}</h2><p>Events are aggregated from relationships, reminders, life events, and study data.</p></div><a className="btn" href="/people">Manage people →</a></section>
    <div className="calendar-toolbar"><div className="calendar-month-nav"><button onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() - 1, 1))}>←</button><strong>{monthLabel(month)}</strong><button onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() + 1, 1))}>→</button><button className="today-button" onClick={() => { const now = new Date(); setMonth(monthStart(now)); setSelectedDate(isoDate(now)); }}>Today</button></div><div className="calendar-filters">{EVENT_TYPES.map((type) => <button key={type} className={activeTypes.has(type) ? "active" : ""} onClick={() => toggleType(type)}><span style={{ background: TYPE_META[type].color }} />{TYPE_META[type].label}</button>)}</div></div>
    <div className="calendar-layout"><section className="calendar-month card"><div className="calendar-weekdays">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => <span key={day}>{day}</span>)}</div><div className="calendar-grid">{days.map((day, index) => { if (!day) return <div className="calendar-day empty" key={`empty-${index}`} />; const key = isoDate(day); const dayEvents = byDate[key] ?? []; return <button key={key} className={`calendar-day${key === selectedDate ? " selected" : ""}${key === todayKey ? " today" : ""}`} onClick={() => setSelectedDate(key)}><span className="calendar-day-number">{day.getDate()}</span>{dayEvents.slice(0, 3).map((event, eventIndex) => <span className="calendar-event-dot" key={`${event.type}-${eventIndex}`} style={{ background: TYPE_META[event.type]?.color ?? "var(--muted)" }} title={event.title} />)}{dayEvents.length > 3 && <small>+{dayEvents.length - 3}</small>}</button>; })}</div></section><aside className="calendar-agenda card"><div className="calendar-agenda-head"><div><h2>{dateLabel(selectedDate)}</h2><p>{selectedEvents.length ? `${selectedEvents.length} scheduled item${selectedEvents.length === 1 ? "" : "s"}` : "Clear day"}</p></div><span className="calendar-count">{selectedEvents.length}</span></div>{selectedEvents.length ? <div className="calendar-event-list">{selectedEvents.map((event, index) => <div className="calendar-event-card" key={`${event.date}-${event.type}-${index}`}><span className="calendar-event-icon" style={{ color: TYPE_META[event.type]?.color }}>{TYPE_META[event.type]?.icon ?? "•"}</span><div><strong>{event.title}</strong><small>{TYPE_META[event.type]?.label ?? event.type} · {event.source?.split(".").pop() ?? "Vesper"}</small></div></div>)}</div> : <div className="data-empty"><div><strong>No plans here</strong><span>Use the people or journal pages to create the next useful event.</span></div></div>}<div className="calendar-upcoming"><h3>Next birthdays</h3>{birthdays.slice(0, 5).map((birthday) => <a href="/people" key={birthday.person_id}><span className="calendar-birthday-avatar">{birthday.name?.slice(0, 1)}</span><span><strong>{birthday.name}</strong><small>{fmtDate(birthday.next ?? birthday.birthday)}</small></span><em>→</em></a>)}{!birthdays.length && <p className="muted">No birthdays in the next 30 days.</p>}</div></aside></div>
  </>;
}
