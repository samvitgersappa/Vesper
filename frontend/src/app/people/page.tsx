"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";

type Person = Record<string, any>;

export default function People() {
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [selected, setSelected] = useState<Person | null>(null);
  const [error, setError] = useState("");

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
      setSelected(await api(`/relationship/person/${id}`));
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <>
      <h1>People</h1>
      {error && <div className="error">{error}</div>}
      <input
        type="search"
        placeholder="Search contacts…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="grid" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Results ({people.length})</h2>
          <ul className="list">
            {people.map((p) => (
              <li key={p.person_id ?? p.id}>
                <a className="link" href="#" onClick={(e) => { e.preventDefault(); open(p.person_id ?? p.id); }}>
                  {p.name}
                </a>
                <span className="muted">{p.category ?? ""}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h2>Detail</h2>
          {selected ? (
            <div>
              <div className="big">{selected.name}</div>
              <p className="muted">
                {selected.category} · last contact{" "}
                {selected.last_contact_date ?? "—"}
              </p>
              <p>{selected.notes ?? selected.summary ?? ""}</p>
              {selected.interactions?.length ? (
                <ul className="list">
                  {selected.interactions.slice(-5).map((i: any) => (
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
            <div className="muted">Select a person to see details.</div>
          )}
        </div>
      </div>
    </>
  );
}
