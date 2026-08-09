"use client";

import { useEffect, useState } from "react";
import { api, apiWrite } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type Person = Record<string, any>;

export default function People() {
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [selected, setSelected] = useState<Person | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<Person>({});

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const res = await api<Record<string, any>>("/relationship/search", {
          query,
          limit: 30,
        });
        setPeople(res.results ?? res.persons ?? res ?? []);
      } catch (e: any) {
        setError(e.message);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  const open = async (id: string) => {
    try {
      const person = await api<Person>(`/relationship/person/${id}`);
      setSelected(person);
      setForm(person);
      setEditing(false);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      const fields = ["name", "nickname", "company", "occupation", "email", "phone", "bio", "profile_notes", "topics_of_interest"];
      for (const field of fields) {
        const value = field === "topics_of_interest"
          ? String(form[field] ?? "")
          : String(form[field] ?? "");
        await apiWrite(`/relationship/person/${selected.id}`, "PATCH", { field, value });
      }
      await open(selected.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Relationships"
        subtitle="Your network, kept warm — search contacts, review last touches and never let a bond go quiet."
        accent="var(--people)"
        accentB="#ff9d6b"
      />
      {error && <div className="error">{error}</div>}
      <input
        className="search-command"
        type="search"
        placeholder="Search contacts…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="section-intro"><div><h2>People radar</h2><p>Search by name, company, or the context you remember.</p></div><span className="muted">{people.length} matches</span></div>
      <div className="grid people-layout">
        <div className="card">
          <h2>Results ({people.length})</h2>
            <ul className="list people-list">
            {people.map((p) => (
              <li key={p.person_id ?? p.id}>
                <a className="link" href="#" onClick={(e) => { e.preventDefault(); open(p.person_id ?? p.id); }}>
                  {p.name}
                </a>
                <span className="muted">{p.category ?? ""}</span>
              </li>
            ))}
            </ul>
            {!people.length && <div className="data-empty"><div><strong>No one surfaced</strong><span>Try a name, company, or relationship.</span></div></div>}
        </div>
        <div className="card">
          <h2>Detail</h2>
          {selected ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div className="big">{selected.name}</div>
                <button className="pill" onClick={() => setEditing((value) => !value)}>{editing ? "Close" : "Edit card"}</button>
              </div>
              {editing && (
                <div className="card" style={{ margin: "16px 0", display: "grid", gap: 10 }}>
                  {[["name", "Name"], ["nickname", "Nickname"], ["company", "Company"], ["occupation", "Occupation"], ["email", "Email"], ["phone", "Phone"], ["bio", "Bio"], ["profile_notes", "Profile notes"], ["topics_of_interest", "Topics of interest (comma separated)"]].map(([field, label]) => (
                    <label key={field} style={{ display: "grid", gap: 5 }}>
                      <span className="muted">{label}</span>
                      {field === "bio" || field === "profile_notes" ? (
                        <textarea value={form[field] ?? ""} onChange={(e) => setForm({ ...form, [field]: e.target.value })} />
                      ) : (
                        <input value={field === "topics_of_interest" ? (form[field] ?? []).join(", ") : form[field] ?? ""} onChange={(e) => setForm({ ...form, [field]: e.target.value })} />
                      )}
                    </label>
                  ))}
                  <button className="btn" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save card"}</button>
                </div>
              )}
              <p className="muted">
                {selected.category} · last contact{" "}
                {selected.last_contacted ?? "—"}
              </p>
              <p>
                {selected.profile_notes ?? selected.summary ?? ""}
                {Array.isArray(selected.notes) && selected.notes.length > 0 &&
                  ` ${selected.notes.map((note: any) => note.content ?? note.text ?? "").join(" ")}`}
              </p>
              {selected.topics_of_interest?.length ? (
                <p className="muted">Topics: {selected.topics_of_interest.join(", ")}</p>
              ) : null}
              {selected.recent_interactions?.length ? (
                <ul className="list">
                  {selected.recent_interactions.slice(-5).map((i: any) => (
                    <li key={i.interaction_id ?? i.id}>
                      <span>{i.type ?? i.interaction_type}</span>
                      <span className="muted">{i.interaction_date ?? ""}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="muted">No interactions logged.</div>
              )}
            </div>
          ) : (
            <div className="data-empty"><div><strong>Choose a person</strong><span>The useful context will appear here.</span></div></div>
          )}
        </div>
      </div>
    </>
  );
}
