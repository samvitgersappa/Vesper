"use client";

import { useEffect, useMemo, useState } from "react";
import { api, apiWrite, fmtDate } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type Person = Record<string, any>;
const CATEGORIES = ["FAMILY", "FRIENDS", "IMPORTANT", "COUSINS", "RELATIVES", "COLLEAGUES", "NEW_CONTACT", "NETWORK"];
const CATEGORY_COLORS: Record<string, string> = { FAMILY: "#fb7185", FRIENDS: "#f59e0b", IMPORTANT: "#facc15", COUSINS: "#c084fc", RELATIVES: "#e879f9", COLLEAGUES: "#2dd4bf", NEW_CONTACT: "#60a5fa", NETWORK: "#94a3b8" };

function health(score?: number) {
  if (score === undefined || score === null) return { label: "No signal", color: "#94a3b8" };
  if (score >= 0.8) return { label: "Healthy", color: "#22c55e" };
  if (score >= 0.4) return { label: "Drifting", color: "#f59e0b" };
  return { label: "Needs attention", color: "#ef4444" };
}

function daysSince(date?: string) {
  if (!date) return null;
  return Math.max(0, Math.floor((Date.now() - new Date(date).getTime()) / 86400000));
}

const blankForm = { name: "", company: "", occupation: "", category: "NETWORK", email: "", phone: "", notes: "" };

export default function People() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("ALL");
  const [people, setPeople] = useState<Person[]>([]);
  const [stats, setStats] = useState<Person>({});
  const [due, setDue] = useState<Person>({});
  const [selected, setSelected] = useState<Person | null>(null);
  const [detail, setDetail] = useState<Person | null>(null);
  const [view, setView] = useState<"board" | "list" | "clusters">("board");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Person>({});
  const [newPerson, setNewPerson] = useState(blankForm);
  const [showAdd, setShowAdd] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [logForm, setLogForm] = useState({ type: "message", summary: "", follow_up_needed: false, follow_up_note: "" });
  const [prep, setPrep] = useState<Person | null>(null);
  const [draft, setDraft] = useState<Person | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [search, networkStats, dueToday] = await Promise.all([
        api<Record<string, any>>("/relationship/search", { query, limit: 100 }),
        api<Record<string, any>>("/relationship/stats"),
        api<Record<string, any>>("/relationship/due-today"),
      ]);
      setPeople(search.results ?? []);
      setStats(networkStats);
      setDue(dueToday);
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { const timer = setTimeout(load, 180); return () => clearTimeout(timer); }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => category === "ALL" ? people : people.filter((p) => p.category === category), [people, category]);
  const columns = useMemo(() => CATEGORIES.reduce<Record<string, Person[]>>((result, item) => { result[item] = filtered.filter((p) => (p.category || "NETWORK") === item); return result; }, {}), [filtered]);
  const clusters = useMemo(() => filtered.reduce<Record<string, Person[]>>((result, person) => { const key = person.cluster_name || person.company || person.category || "Network"; (result[key] ??= []).push(person); return result; }, {}), [filtered]);
  const overdue = Array.isArray(due.overdue) ? due.overdue : [];

  const open = async (person: Person) => {
    try {
      const loaded = await api<Person>(`/relationship/person/${person.id ?? person.person_id}`);
      setSelected(loaded); setDetail(loaded); setForm(loaded); setEditing(false); setPrep(null); setDraft(null);
    } catch (e: any) { setError(e.message); }
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true); setError("");
    try {
      const fields = ["name", "nickname", "company", "occupation", "email", "phone", "bio", "profile_notes", "topics_of_interest", "category"];
      for (const field of fields) {
        const value = field === "topics_of_interest" ? String(form[field] ?? "") : String(form[field] ?? "");
        if (value !== String(selected[field] ?? "")) await apiWrite(`/relationship/person/${selected.id}`, "PATCH", { field, value });
      }
      await load(); await open(selected);
    } catch (e: any) { setError(e.message); } finally { setSaving(false); }
  };

  const addPerson = async () => {
    if (!newPerson.name.trim()) return;
    setSaving(true); setError("");
    try { const created = await apiWrite<Person>("/relationship/person", "POST", newPerson); setShowAdd(false); setNewPerson(blankForm); await load(); if (created.id) await open(created); }
    catch (e: any) { setError(e.message); } finally { setSaving(false); }
  };

  const logInteraction = async () => {
    if (!selected) return;
    setSaving(true);
    try { await apiWrite(`/relationship/person/${selected.id}/interactions`, "POST", logForm); setShowLog(false); setLogForm({ type: "message", summary: "", follow_up_needed: false, follow_up_note: "" }); await load(); await open(selected); }
    catch (e: any) { setError(e.message); } finally { setSaving(false); }
  };

  const generatePrep = async () => { if (!selected) return; try { setPrep(await api<Record<string, any>>(`/relationship/person/${selected.id}/meeting-prep`)); } catch (e: any) { setError(e.message); } };
  const generateDraft = async () => { if (!selected) return; try { setDraft(await apiWrite<Record<string, any>>(`/relationship/person/${selected.id}/draft-message`, "POST", { purpose: "reconnect" })); } catch (e: any) { setError(e.message); } };

  return <>
    <PageHeader title="People OS" subtitle="Keep the people who matter visible, healthy, and easy to act on." accent="var(--people)" accentB="#ff9d6b" />
    {error && <div className="error">{error}</div>}
    <div className="people-summary"><div><strong>{stats.total_contacts ?? people.length}</strong><span>contacts</span></div><div><strong>{stats.interactions_this_week ?? 0}</strong><span>touches this week</span></div><div><strong className={stats.cold_contacts ? "bad" : "good"}>{stats.cold_contacts ?? 0}</strong><span>going cold</span></div><div><strong>{overdue.length}</strong><span>open loops</span></div></div>
    <div className="people-toolbar"><div className="people-search"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search people, companies, or roles…" /></div><div className="people-toolbar-actions"><button className={view === "board" ? "active" : ""} onClick={() => setView("board")}>▦ Board</button><button className={view === "clusters" ? "active" : ""} onClick={() => setView("clusters")}>◌ Clusters</button><button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>☷ List</button><button className="people-add" onClick={() => setShowAdd(true)}>＋ Add person</button></div></div>
    <div className="people-filters"><button className={category === "ALL" ? "active" : ""} onClick={() => setCategory("ALL")}>All <em>{people.length}</em></button>{CATEGORIES.map((c) => <button key={c} className={category === c ? "active" : ""} onClick={() => setCategory(c)}><span style={{ background: CATEGORY_COLORS[c] }} />{c.replace("_", " ")} <em>{people.filter((p) => p.category === c).length}</em></button>)}</div>
    {view === "board" ? <div className="people-board">{CATEGORIES.map((c) => <section className="people-column" key={c}><header><span className="category-dot" style={{ background: CATEGORY_COLORS[c] }} /><strong>{c.replace("_", " ")}</strong><em>{columns[c]?.length ?? 0}</em></header><div className="people-column-body">{(columns[c] ?? []).map((person) => <PersonCard key={person.id} person={person} onOpen={() => open(person)} />)}{!columns[c]?.length && <div className="column-empty">No contacts</div>}</div></section>)}</div> : view === "clusters" ? <div className="people-clusters">{Object.entries(clusters).map(([cluster, members]) => <section className="people-cluster" key={cluster}><header><div><span className="eyebrow">Cluster</span><h2>{cluster}</h2></div><strong>{members.length}</strong></header><div className="people-cluster-members">{members.map((person) => <PersonCard key={person.id} person={person} onOpen={() => open(person)} />)}</div></section>)}{!Object.keys(clusters).length && <div className="data-empty"><div><strong>No clusters yet</strong><span>Add company or relationship context to form a useful circle.</span></div></div>}</div> : <div className="people-list-view">{filtered.map((person) => <PersonRow key={person.id} person={person} onOpen={() => open(person)} />)}{!filtered.length && <div className="data-empty"><div><strong>No one surfaced</strong><span>Try a name, company, or relationship.</span></div></div>}</div>}
    {selected && <aside className="people-inspector"><button className="people-inspector-close" onClick={() => setSelected(null)}>×</button><div className="people-inspector-head"><div className="person-avatar" style={{ background: CATEGORY_COLORS[selected.category ?? "NETWORK"] }}>{selected.name?.slice(0, 1)}</div><div><h2>{selected.name}</h2><p>{selected.company || selected.occupation || selected.category}</p></div></div><div className="people-actions"><button onClick={() => setShowLog(true)}>⚡ Log touch</button><button onClick={generatePrep}>✦ Meeting prep</button><button onClick={generateDraft}>✎ Draft message</button><button onClick={() => setEditing((v) => !v)}>{editing ? "Close edit" : "Edit card"}</button></div><div className="people-health"><div><strong style={{ color: health(selected.health_score).color }}>{Math.round((selected.health_score ?? 0) * 100)}%</strong><span>{health(selected.health_score).label}</span></div><div><strong>{daysSince(selected.last_contacted) ?? "—"}{daysSince(selected.last_contacted) !== null && "d"}</strong><span>since last touch</span></div><div><strong>{selected.streak_weeks ?? 0}w</strong><span>streak</span></div></div>{editing && <EditForm form={form} setForm={setForm} onSave={save} saving={saving} />}{!editing && <><section className="people-detail-section"><h3>Context</h3><div className="people-context-facts"><span><b>Relationship</b>{selected.category || "NETWORK"}</span><span><b>Cluster</b>{selected.cluster_name || selected.company || selected.category || "Network"}</span>{selected.company && <span><b>Company</b>{selected.company}</span>}{selected.occupation && <span><b>Role</b>{selected.occupation}</span>}</div><p>{selected.profile_notes || selected.bio || "Context will grow as you mention this person in journal entries."}</p>{selected.topics_of_interest?.length ? <div className="people-tags">{selected.topics_of_interest.map((tag: string) => <span key={tag}>{tag}</span>)}</div> : null}</section><section className="people-detail-section"><h3>Recent interactions</h3>{detail?.recent_interactions?.slice(0, 5).map((interaction: any) => <div className="people-event" key={interaction.id}><strong>{interaction.type}</strong><span>{interaction.summary || "Interaction logged"}</span><small>{fmtDate(interaction.date)}</small></div>)}{!detail?.recent_interactions?.length && <p className="muted">No interactions logged.</p>}</section></>}{prep && <section className="people-output"><h3>Meeting prep</h3><p>{prep.last_interaction?.summary || prep.person?.profile_notes || "No recent context found."}</p>{prep.open_follow_ups?.map((item: any) => <p key={item.id}>Follow up: {item.follow_up_note || item.summary}</p>)}</section>}{draft && <section className="people-output"><h3>Draft message <button onClick={() => navigator.clipboard?.writeText(draft.draft)}>Copy</button></h3><p className="preserve-lines">{draft.draft}</p><small>Draft only. Nothing was sent.</small></section>}<a className="people-full-profile" href="/graph">View this relationship in the map →</a></aside>}
    {showAdd && <Modal title="Add person" close={() => setShowAdd(false)}><div className="people-form">{[["name", "Name *"], ["company", "Company"], ["occupation", "Role"], ["email", "Email"], ["phone", "Phone"]].map(([key, label]) => <label key={key}><span>{label}</span><input value={newPerson[key as keyof typeof newPerson]} onChange={(e) => setNewPerson({ ...newPerson, [key]: e.target.value })} /></label>)}<label><span>Category</span><select value={newPerson.category} onChange={(e) => setNewPerson({ ...newPerson, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label><label><span>Initial note</span><textarea value={newPerson.notes} onChange={(e) => setNewPerson({ ...newPerson, notes: e.target.value })} /></label><button className="people-add" onClick={addPerson} disabled={saving}>{saving ? "Adding…" : "Add person"}</button></div></Modal>}
    {showLog && <Modal title={`Log a touch with ${selected?.name}`} close={() => setShowLog(false)}><div className="people-form"><label><span>Type</span><select value={logForm.type} onChange={(e) => setLogForm({ ...logForm, type: e.target.value })}><option>message</option><option>call</option><option>meeting</option><option>email</option><option>social</option></select></label><label><span>What happened?</span><textarea autoFocus value={logForm.summary} onChange={(e) => setLogForm({ ...logForm, summary: e.target.value })} placeholder="Captured the important context…" /></label><label className="check-row"><input type="checkbox" checked={logForm.follow_up_needed} onChange={(e) => setLogForm({ ...logForm, follow_up_needed: e.target.checked })} /><span>Needs follow-up</span></label>{logForm.follow_up_needed && <label><span>Follow-up note</span><input value={logForm.follow_up_note} onChange={(e) => setLogForm({ ...logForm, follow_up_note: e.target.value })} /></label>}<button className="people-add" onClick={logInteraction} disabled={saving || !logForm.summary.trim()}>{saving ? "Saving…" : "Save interaction"}</button></div></Modal>}
  </>;
}

function PersonCard({ person, onOpen }: { person: Person; onOpen: () => void }) { return <button className="person-card" onClick={onOpen}><div className="person-card-top"><span className="person-avatar small" style={{ background: CATEGORY_COLORS[person.category ?? "NETWORK"] }}>{person.name?.slice(0, 1)}</span><span><strong>{person.name}</strong><small>{person.company || person.occupation || "No organization"}</small></span></div><div className="person-card-bottom"><span className="health-bar"><i style={{ width: `${Math.round((person.health_score ?? 0) * 100)}%`, background: health(person.health_score).color }} /></span><span style={{ color: health(person.health_score).color }}>{Math.round((person.health_score ?? 0) * 100)}</span>{person.last_contacted && <small>{daysSince(person.last_contacted)}d ago</small>}</div></button>; }
function PersonRow({ person, onOpen }: { person: Person; onOpen: () => void }) { return <button className="person-row" onClick={onOpen}><span className="person-avatar small" style={{ background: CATEGORY_COLORS[person.category ?? "NETWORK"] }}>{person.name?.slice(0, 1)}</span><span className="person-row-name"><strong>{person.name}</strong><small>{person.company || person.occupation || "No organization"}</small></span><span className="person-row-category">{person.category}</span><span className="person-row-health" style={{ color: health(person.health_score).color }}>{Math.round((person.health_score ?? 0) * 100)}%</span><span className="muted">{person.last_contacted ? `${daysSince(person.last_contacted)}d ago` : "Never contacted"}</span></button>; }
function EditForm({ form, setForm, onSave, saving }: { form: Person; setForm: (f: Person) => void; onSave: () => void; saving: boolean }) { return <div className="people-form edit-form">{[["name", "Name"], ["nickname", "Nickname"], ["company", "Company"], ["occupation", "Role"], ["email", "Email"], ["phone", "Phone"]].map(([key, label]) => <label key={key}><span>{label}</span><input value={form[key] ?? ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></label>)}<label><span>Category</span><select value={form.category ?? "NETWORK"} onChange={(e) => setForm({ ...form, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label><label><span>Profile notes</span><textarea value={form.profile_notes ?? ""} onChange={(e) => setForm({ ...form, profile_notes: e.target.value })} /></label><label><span>Topics, comma separated</span><input value={Array.isArray(form.topics_of_interest) ? form.topics_of_interest.join(", ") : form.topics_of_interest ?? ""} onChange={(e) => setForm({ ...form, topics_of_interest: e.target.value })} /></label><button className="people-add" onClick={onSave} disabled={saving}>{saving ? "Saving…" : "Save card"}</button></div>; }
function Modal({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) { return <div className="people-modal-backdrop" onClick={close}><div className="people-modal" onClick={(e) => e.stopPropagation()}><header><h2>{title}</h2><button onClick={close}>×</button></header>{children}</div></div>; }
