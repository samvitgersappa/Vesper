"use client";

import { usePathname } from "next/navigation";
import PageHeader from "../../../components/PageHeader";

const QUARTZ_DEV_ORIGIN =
  process.env.NODE_ENV === "development" ? "http://127.0.0.1:8081" : null;

export default function Brain() {
  const pathname = usePathname() ?? "/brain/";
  const rest = pathname.replace(/^\/brain\/?/, "");
  const src = QUARTZ_DEV_ORIGIN ? `${QUARTZ_DEV_ORIGIN}/${rest}` : null;

  return (
    <>
      <PageHeader
        title="Second Brain"
        subtitle="The Vesper Quartz garden — every note Hermes has ever written, as a navigable graph of knowledge."
        accent="var(--graph)"
        accentB="#b980f7"
      />
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 12,
          overflow: "hidden",
          background: "var(--panel)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 10,
            padding: "10px 14px",
            borderBottom: "1px solid var(--border)",
            background: "var(--panel-2)",
            fontSize: 13,
            color: "var(--muted)",
          }}
        >
          <span>Vesper Second Brain — Quartz v5 garden</span>
          {QUARTZ_DEV_ORIGIN && <a href="http://127.0.0.1:8081/" style={{ color: "var(--graph)" }}>garden root →</a>}
        </div>
        {src ? (
          <iframe
            src={src}
            title="Second Brain garden"
            style={{ width: "100%", height: "78vh", border: 0, display: "block" }}
          />
        ) : (
          <p className="muted" style={{ padding: 24 }}>
            The garden is served by Vesper at /brain in production.
          </p>
        )}
      </div>
      <p className="muted" style={{ marginTop: 12 }}>
        In development the garden loads from the local Quartz server (port 8081).
        In production Caddy serves the built garden straight from the quartz
        volume at /brain.
      </p>
    </>
  );
}
