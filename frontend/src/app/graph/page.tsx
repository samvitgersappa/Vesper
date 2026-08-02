"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Node = { id: string; label: string; type: string; group?: number };
type Edge = { source: string; target: string; weight?: number };
type GData = { nodes: Node[]; edges: Edge[] };

export default function Graph() {
  const [data, setData] = useState<GData>({ nodes: [], edges: [] });
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Node | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const [nodesRes, edgesRes] = await Promise.all([
          api<Record<string, any>>("/graph/nodes", { limit: 200 }),
          api<Record<string, any>>("/graph/edges", { limit: 400 }),
        ]);
        const nodes = nodesRes.nodes ?? nodesRes ?? [];
        const edges = edgesRes.edges ?? edgesRes ?? [];
        setData({
          nodes: (nodes as any[]).map((n: any) => ({
            id: String(n.id ?? n.node_id ?? n.name),
            label: n.name ?? n.label ?? n.id ?? String(n.node_id ?? "?"),
            type: n.node_type ?? n.type ?? "node",
            group: n.group,
          })),
          edges: (edges as any[]).map((e: any) => ({
            source: String(e.source ?? e.from ?? ""),
            target: String(e.target ?? e.to ?? ""),
            weight: e.weight,
          })),
        });
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  useEffect(() => {
    if (!data.nodes.length || !svgRef.current) return;
    draw(svgRef.current, data, setSelected);
  }, [data]);

  return (
    <>
      <h1>Graph OS</h1>
      {error && <div className="error">{error}</div>}
      {!data.nodes.length && !error && (
        <div className="muted">
          Graph is empty — nodes populate as the write adapter processes
          events (PersonUpdated, InteractionLogged, KnowledgeIndexed).
        </div>
      )}
      <svg
        ref={svgRef}
        width="100%"
        height="560"
        style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 12 }}
      />
      {selected && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>
            {selected.label} <span className="pill">{selected.type}</span>
          </h2>
          <div className="muted">Click a node to inspect. Reloads when the graph adapter runs.</div>
        </div>
      )}
    </>
  );
}

const COLORS: Record<string, string> = {
  person: "#6ea8fe",
  interaction: "#d8a94e",
  note: "#4caf7d",
  project: "#c792ea",
  calendar: "#56b6c2",
  study: "#e06c75",
  finance: "#e5c07b",
};

function draw(
  svg: SVGSVGElement,
  data: GData,
  onSelect: (n: Node | null) => void,
) {
  const W = svg.clientWidth || 1100;
  const H = svg.clientHeight || 560;
  const nodes = data.nodes.map((n) => ({ ...n, x: Math.random() * W, y: Math.random() * H }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = data.edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => ({ a: byId.get(e.source)!, b: byId.get(e.target)! }));

  // Simple force layout (repulsion + springs toward center).
  for (let iter = 0; iter < 120; iter++) {
    for (const n of nodes) {
      for (const m of nodes) {
        if (n === m) continue;
        const dx = n.x - m.x;
        const dy = n.y - m.y;
        const d2 = dx * dx + dy * dy || 1;
        const f = 600 / d2;
        n.x += (dx / Math.sqrt(d2)) * f;
        n.y += (dy / Math.sqrt(d2)) * f;
      }
      n.x += (W / 2 - n.x) * 0.02;
      n.y += (H / 2 - n.y) * 0.02;
    }
    for (const e of edges) {
      const dx = e.b.x - e.a.x;
      const dy = e.b.y - e.a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const pull = (d - 90) * 0.04;
      e.a.x += (dx / d) * pull;
      e.a.y += (dy / d) * pull;
      e.b.x -= (dx / d) * pull;
      e.b.y -= (dy / d) * pull;
    }
  }

  svg.innerHTML = "";
  const NS = "http://www.w3.org/2000/svg";

  for (const e of edges) {
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", String(e.a.x));
    line.setAttribute("y1", String(e.a.y));
    line.setAttribute("x2", String(e.b.x));
    line.setAttribute("y2", String(e.b.y));
    line.setAttribute("stroke", "#3a4150");
    line.setAttribute("stroke-width", "1");
    svg.appendChild(line);
  }

  for (const n of nodes) {
    const g = document.createElementNS(NS, "g");
    const r = n.type === "person" ? 9 : 6;
    const circle = document.createElementNS(NS, "circle");
    circle.setAttribute("r", String(r));
    circle.setAttribute("fill", COLORS[n.type] ?? "#8b93a3");
    circle.setAttribute("cx", String(n.x));
    circle.setAttribute("cy", String(n.y));
    g.appendChild(circle);
    const text = document.createElementNS(NS, "text");
    text.textContent = n.label;
    text.setAttribute("x", String(n.x + r + 3));
    text.setAttribute("y", String(n.y + 4));
    text.setAttribute("fill", "#8b93a3");
    text.setAttribute("font-size", "11");
    g.appendChild(text);
    g.style.cursor = "pointer";
    g.addEventListener("click", () => onSelect(n));
    svg.appendChild(g);
  }
}
