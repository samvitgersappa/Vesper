"use client";

import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

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
      <PageHeader
        title="Learning"
        subtitle="Exam readiness and your revision pipeline — know exactly how prepared you are before test day."
        accent="var(--study)"
        accentB="#9d7bff"
      />
      {error && <div className="error">{error}</div>}
      <section className="study-banner"><div className="study-ring"><span>{readiness?.readiness && readiness.readiness !== "no_data" ? `${readiness.readiness}%` : "—"}</span></div><div><span className="eyebrow">Readiness signal</span><h2>{tests.length ? `${tests.length} test${tests.length === 1 ? "" : "s"} in the pipeline` : "Build your first checkpoint"}</h2><p>{readiness?.message ?? "A small, regular test is more useful than a heroic revision sprint."}</p></div></section>
      <div className="grid">
        <div className="card">
          <h2>Exam Readiness</h2>
          <div className="big grad" style={{ "--big-a": "#5b8cff", "--big-b": "#9d7bff" } as React.CSSProperties}>
            {readiness?.readiness && readiness.readiness !== "no_data"
              ? `${readiness.readiness}%`
              : "—"}
          </div>
          <div className="muted">
            {readiness?.message ?? readiness?.target_date ?? ""}
          </div>
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
          {!tests.length && <div className="data-empty"><div><strong>No checkpoints yet</strong><span>Tests become your learning feedback loop.</span></div></div>}
        </div>
      </div>
    </>
  );
}
