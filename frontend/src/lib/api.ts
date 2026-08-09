const CONFIGURED_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "");
export const API_BASE = CONFIGURED_BASE || (
  typeof window === "undefined"
    ? "http://localhost:8000"
    : ""
);

export async function api<T = unknown>(
  path: string,
  params: Record<string, string | number | undefined> = {},
): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const url = `${API_BASE}/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export async function apiWrite<T = unknown>(
  path: string,
  method: "PATCH" | "POST",
  body: Record<string, unknown>,
): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const responseBody = await res.text();
    throw new Error(`${res.status}: ${responseBody.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export function fmtDate(d?: string): string {
  if (!d) return "—";
  return new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString(
    "en-IN",
    { day: "numeric", month: "short" },
  );
}
