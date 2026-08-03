"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from "d3-force";
import { drag } from "d3-drag";
import { zoom } from "d3-zoom";
import { pointer, select } from "d3-selection";
import { api } from "../../lib/api";
import PageHeader from "../../components/PageHeader";

type RawNode = {
  id: string;
  entity_type: string;
  label: string;
  ref_id?: string;
  metadata?: Record<string, any>;
  degree: number;
};
type RawEdge = {
  source_id: string;
  target_id: string;
  edge_type: string;
  weight: number;
};
type GNode = RawNode & { x?: number; y?: number; fx?: number | null; fy?: number | null };
type GEdge = RawEdge & { source: any; target: any };

const NODE_COLORS: Record<string, string> = {
  person: "#6ea8fe",
  interaction: "#d8a94e",
  note: "#4caf7d",
  project: "#c792ea",
  calendar: "#56b6c2",
  study: "#e06c75",
  finance: "#e5c07b",
};
const EDGE_COLORS: Record<string, string> = {
  participated: "#d8a94e",
  introduced_by: "#6ea8fe",
  related: "#8b93a3",
};

const TYPE_ORDER = ["person", "interaction", "note"];

function nodeRadius(t: string) {
  return t === "person" ? 12 : t === "interaction" ? 8 : 6;
}

export default function Graph() {
  const [raw, setRaw] = useState<{ nodes: RawNode[]; edges: RawEdge[] }>({ nodes: [], edges: [] });
  const [error, setError] = useState("");
  const [enabled, setEnabled] = useState<Set<string>>(new Set(TYPE_ORDER));
  const [selected, setSelected] = useState<GNode | null>(null);
  const [detail, setDetail] = useState<{ loading: boolean; data: any }>({ loading: false, data: null });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; label: string; sub: string } | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hoveredRef = useRef<string | null>(null);
  const selectedRef = useRef<GNode | null>(null);
  selectedRef.current = selected;

  useEffect(() => {
    (async () => {
      try {
        const [nodesRes, edgesRes] = await Promise.all([
          api<Record<string, any>>("/graph/nodes", { limit: 2000 }),
          api<Record<string, any>>("/graph/edges", { limit: 4000 }),
        ]);
        const nlist = (nodesRes.nodes ?? nodesRes ?? []) as any[];
        const elist = (edgesRes.edges ?? edgesRes ?? []) as any[];
        const deg = new Map<string, number>();
        for (const e of elist) {
          deg.set(String(e.source_id), (deg.get(String(e.source_id)) ?? 0) + 1);
          deg.set(String(e.target_id), (deg.get(String(e.target_id)) ?? 0) + 1);
        }
        setRaw({
          nodes: nlist.map((n) => ({
            id: String(n.id ?? n.node_id ?? n.name),
            entity_type: n.entity_type ?? n.node_type ?? n.type ?? "node",
            label: n.label ?? n.name ?? n.id ?? "?",
            ref_id: n.ref_id,
            metadata: n.metadata ?? {},
            degree: deg.get(String(n.id)) ?? 0,
          })),
          edges: elist.map((e) => ({
            source_id: String(e.source_id ?? e.source ?? e.from),
            target_id: String(e.target_id ?? e.target ?? e.to),
            edge_type: e.edge_type ?? e.type ?? "related",
            weight: Number(e.weight) || 1,
          })),
        });
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, []);

  const types = useMemo(() => {
    const order = new Map(TYPE_ORDER.map((t, i) => [t, i]));
    const uniq = Array.from(new Set(raw.nodes.map((n) => n.entity_type)));
    return uniq.sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99));
  }, [raw.nodes]);

  const filtered = useMemo(() => {
    const nodeIds = new Set(raw.nodes.filter((n) => enabled.has(n.entity_type)).map((n) => n.id));
    const nodes = raw.nodes.filter((n) => enabled.has(n.entity_type));
    const edges = raw.edges.filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id));
    return { nodes, edges };
  }, [raw, enabled]);

  const adjacency = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of filtered.edges) {
      m.set(e.source_id, (m.get(e.source_id) ?? new Set()).add(e.target_id));
      m.set(e.target_id, (m.get(e.target_id) ?? new Set()).add(e.source_id));
    }
    return m;
  }, [filtered]);

  const toggleType = (t: string) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  useEffect(() => {
    if (!filtered.nodes.length || !svgRef.current) return;
    const svgEl = svgRef.current;
    const W = svgEl.clientWidth || 1100;
    const H = svgEl.clientHeight || 600;

    const svg = select(svgEl);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${W} ${H}`);

    const defs = svg.append("defs");
    for (const et of Object.keys(EDGE_COLORS)) {
      const m = defs
        .append("marker")
        .attr("id", `arrow-${et}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 22)
        .attr("refY", 0)
        .attr("markerWidth", 7)
        .attr("markerHeight", 7)
        .attr("orient", "auto");
      m.append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", EDGE_COLORS[et]);
    }

    const rootG = svg.append("g");
    const edgeG = rootG.append("g");
    const nodeG = rootG.append("g");

    const simNodes: GNode[] = filtered.nodes.map((n) => ({ ...n }));
    const simEdges = filtered.edges.map((e) => ({ ...e, source: e.source_id, target: e.target_id })) as GEdge[];

    const simulation = forceSimulation<GNode>(simNodes as GNode[])
      .force(
        "link",
        forceLink<GNode, GEdge>(simEdges)
          .id((d) => d.id)
          .distance(110)
          .strength(0.5),
      )
      .force("charge", forceManyBody().strength(-240))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide<GNode>().radius((d) => nodeRadius(d.entity_type) + 10))
      .force("x", forceX(W / 2).strength(0.07))
      .force("y", forceY(H / 2).strength(0.07));

    const line = edgeG
      .selectAll("line")
      .data(simEdges)
      .join("line")
      .attr("stroke", (e: GEdge) => EDGE_COLORS[e.edge_type] ?? EDGE_COLORS.related)
      .attr("stroke-width", (e: GEdge) => Math.min(1.5 + e.weight, 4))
      .attr("stroke-opacity", 0.65)
      .attr("marker-end", (e: GEdge) => `url(#arrow-${e.edge_type})`);

    const nodeSel = nodeG
      .selectAll("g.node")
      .data(simNodes)
      .join("g")
      .attr("class", "node")
      .style("cursor", "pointer");

    nodeSel
      .append("circle")
      .attr("r", (d) => nodeRadius(d.entity_type))
      .attr("fill", (d) => NODE_COLORS[d.entity_type] ?? "#8b93a3");

    nodeSel
      .append("text")
      .attr("class", "nlabel")
      .attr("x", (d) => nodeRadius(d.entity_type) + 4)
      .attr("y", 4)
      .attr("font-size", 11)
      .attr("fill", "#c9d1d9");

    let dragged = false;

    nodeSel
      .on("mouseenter", (event, d: GNode) => {
        hoveredRef.current = d.id;
        const [mx, my] = pointer(event, svgEl);
        setTooltip({ x: mx, y: my, label: d.label, sub: `${d.entity_type}${d.ref_id ? " · " + d.ref_id : ""}` });
        applyActive();
      })
      .on("mousemove", (event) => {
        const [mx, my] = pointer(event, svgEl);
        setTooltip((t) => (t ? { ...t, x: mx, y: my } : t));
      })
      .on("mouseleave", () => {
        hoveredRef.current = null;
        setTooltip(null);
        applyActive();
      })
      .on("click", (event, d: GNode) => {
        if (dragged) return;
        event.stopPropagation();
        selectNode(d);
      });

    (nodeSel as any).call(
      drag<SVGGElement, GNode>()
        .on("start", (event, d) => {
          dragged = false;
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
          event.sourceEvent?.stopPropagation();
        })
        .on("drag", (event, d) => {
          dragged = true;
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }),
    );

    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 5])
      .on("zoom", (event) => rootG.attr("transform", event.transform));
    svg.call(zoomBehavior);
    svg.on("dblclick.zoom", null);

    const shown = (d: GNode) =>
      d.entity_type === "person" || hoveredRef.current === d.id || selectedRef.current?.id === d.id;

    function applyActive() {
      const active = new Set<string>();
      const hover = hoveredRef.current;
      const sel = selectedRef.current?.id ?? null;
      if (hover) {
        active.add(hover);
        (adjacency.get(hover) ?? []).forEach((n) => active.add(n));
      }
      if (sel) {
        active.add(sel);
        (adjacency.get(sel) ?? []).forEach((n) => active.add(n));
      }
      nodeSel.attr("opacity", (d: GNode) => {
        if (!hover && !sel) return 1;
        return active.has(d.id) ? 1 : 0.18;
      });
      line.attr("stroke-opacity", (e: GEdge) => {
        const s = String(e.source?.id ?? e.source);
        const t = String(e.target?.id ?? e.target);
        if (!hover && !sel) return 0.65;
        return active.has(s) && active.has(t) ? 0.95 : 0.08;
      });
      nodeSel.select("text").text((d: GNode) => (shown(d) ? d.label : ""));
    }

    simulation.on("tick", () => {
      line
        .attr("x1", (e: GEdge) => e.source.x)
        .attr("y1", (e: GEdge) => e.source.y)
        .attr("x2", (e: GEdge) => e.target.x)
        .attr("y2", (e: GEdge) => e.target.y);
      nodeSel.attr("transform", (d: GNode) => `translate(${d.x},${d.y})`);
      applyActive();
    });

    svg.on("click", () => setSelected(null));

    return () => {
      simulation.stop();
      svg.on(".zoom", null);
      svg.on("click", null);
    };
  }, [filtered, adjacency]);

  const selectNode = useCallback(
    async (n: GNode) => {
      setSelected(n);
      setDetail({ loading: true, data: null });
      if (n.entity_type === "person" && n.ref_id) {
        try {
          const d = await api<Record<string, any>>(`/relationship/person/${n.ref_id}`);
          setDetail({ loading: false, data: { kind: "person", payload: d } });
        } catch (e: any) {
          setDetail({ loading: false, data: { kind: "person", error: e.message } });
        }
      } else if (n.entity_type === "note") {
        setDetail({
          loading: false,
          data: { kind: "note", payload: { label: n.label, vault_path: n.metadata?.vault_path ?? n.ref_id } },
        });
      } else {
        setDetail({ loading: false, data: { kind: "interaction", payload: n } });
      }
    },
    [],
  );

  const gardenLink = (rel: string) => {
    if (!rel) return "#";
    const slug = rel.replace(/\.md$/i, "").toLowerCase().split(" ").join("-");
    const encoded = slug.split("/").map(encodeURIComponent).join("/");
    const dev = process.env.NODE_ENV === "development";
    return dev
      ? `http://127.0.0.1:8081/${encoded}`
      : `${window.location.origin}/brain/${encoded}`;
  };

  const counts = useMemo(() => {
    const c = new Map<string, number>();
    for (const n of raw.nodes) c.set(n.entity_type, (c.get(n.entity_type) ?? 0) + 1);
    return c;
  }, [raw.nodes]);

  return (
    <>
      <PageHeader
        title="Intelligence Graph"
        subtitle="Everything Vesper knows, connected — people, interactions, notes and projects as one living network. Drag nodes, scroll to zoom, click to inspect."
        accent="var(--graph)"
        accentB="#9d7bff"
      />
      {error && <div className="error">{error}</div>}
      {!raw.nodes.length && !error && (
        <div className="muted">
          Graph is empty — nodes populate as the write adapter processes
          events (PersonUpdated, InteractionLogged, KnowledgeIndexed).
        </div>
      )}

      {raw.nodes.length > 0 && (
        <div
          ref={containerRef}
          style={{ position: "relative", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", background: "var(--panel)" }}
        >
          <div className="graph-toolbar">
            <span className="graph-stats">
              {raw.nodes.length} nodes · {filtered.edges.length} connections
            </span>
            <span className="graph-legend">
              {types.map((t) => (
                <button
                  key={t}
                  className={enabled.has(t) ? "legend-chip on" : "legend-chip"}
                  onClick={() => toggleType(t)}
                  title={enabled.has(t) ? "Click to hide" : "Click to show"}
                >
                  <span className="swatch" style={{ background: NODE_COLORS[t] ?? "#8b93a3" }} />
                  {t} <span className="n">({counts.get(t) ?? 0})</span>
                </button>
              ))}
            </span>
          </div>
          <svg ref={svgRef} width="100%" height="600" style={{ display: "block" }} />
          {tooltip && (
            <div
              className="graph-tooltip"
              style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
            >
              <strong>{tooltip.label}</strong>
              <span>{tooltip.sub}</span>
            </div>
          )}
          {selected && (
            <div className="graph-detail" onClick={(e) => e.stopPropagation()}>
              <h3>
                {selected.label} <span className="pill">{selected.entity_type}</span>
              </h3>
              {detail.loading ? (
                <div className="muted">Loading…</div>
              ) : detail.data?.kind === "person" ? (
                detail.data.error ? (
                  <div className="error">{detail.data.error}</div>
                ) : (
                  <DetailPerson data={detail.data.payload} />
                )
              ) : detail.data?.kind === "note" ? (
                <DetailNote data={detail.data.payload} gardenLink={gardenLink} />
              ) : detail.data?.kind === "interaction" ? (
                <DetailInteraction node={selected} />
              ) : null}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function DetailPerson({ data }: { data: any }) {
  return (
    <div className="detail-body">
      {data.found === false && <div className="muted">{data.message}</div>}
      {data.found !== false && (
        <>
          <div className="detail-grid">
            <div><span className="k">Category</span><span className="v">{data.category ?? "—"}</span></div>
            <div><span className="k">Health</span><span className="v">{data.health_score ?? "—"}</span></div>
            <div><span className="k">Company</span><span className="v">{data.company ?? "—"}</span></div>
            <div><span className="k">Occupation</span><span className="v">{data.occupation ?? "—"}</span></div>
          </div>
          {(data.tags ?? []).length > 0 && (
            <p className="tags">{data.tags.map((t: string) => <span key={t} className="tag">{t}</span>)}</p>
          )}
          {(data.recent_interactions ?? []).length > 0 && (
            <ul className="detail-list">
              {(data.recent_interactions as any[]).slice(0, 5).map((i: any) => (
                <li key={i.id ?? i.event_date}>
                  <strong>{i.type ?? "interaction"}</strong> · {i.event_date ?? "—"}
                  {i.summary ? <span> — {i.summary}</span> : null}
                </li>
              ))}
            </ul>
          )}
          <a className="btn" href="/people/" style={{ marginTop: 12, display: "inline-block" }}>
            Open profile →
          </a>
        </>
      )}
    </div>
  );
}

function DetailNote({ data, gardenLink }: { data: any; gardenLink: (rel: string) => string }) {
  const href = gardenLink(data.vault_path);
  return (
    <div className="detail-body">
      <div className="muted" style={{ wordBreak: "break-all" }}>{data.vault_path ?? "—"}</div>
      {href !== "#" && (
        <a className="btn" href={href} target="_blank" rel="noreferrer" style={{ marginTop: 12, display: "inline-block" }}>
          Open in garden ↗
        </a>
      )}
    </div>
  );
}

function DetailInteraction({ node }: { node: GNode }) {
  const meta = node.metadata ?? {};
  return (
    <div className="detail-body">
      <div className="detail-grid">
        <div><span className="k">Type</span><span className="v">{meta.type ?? "—"}</span></div>
        <div><span className="k">Date</span><span className="v">{node.label.replace("interaction ", "")}</span></div>
      </div>
      {meta.summary && <p>{meta.summary}</p>}
    </div>
  );
}
