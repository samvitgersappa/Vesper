"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";

export default function Study() {
  const [readiness, setReadiness] = useState<any>(null);
  const [tests, setTests] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [r, t] = await Promise.all([
          api<Record<string, any>>("/study/readiness"),
          api<Record<string, any>>("/study/tests"),
        ]);
        setReadiness(r);
        setTests(t.tests ?? t ?? []);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  return (
    <>
      <h1>Study</h1>
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <div className="card">
          <h2>Exam readiness</h2>
          <div className="big">{readiness?.readiness ?? "—"}%</div>
          <div className="muted">{readiness?.target_date ?? ""}</div>
        </div>
        <div className="card">
          <h2>Tests ({tests.length})</h2>
          <ul className="list">
            {tests.map((t) => (
              <li key={t.test_id ?? t.id}>
                <span>{t.name ?? t.test_name}</span>
                <span className="muted">{t.test_date ?? t.scheduled_date ?? ""}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
